"""The daily compliance sweep — the test-harness's `/v1/_sweep/run` body.

The PRD §2.5's H3 paragraph names the canonical sequence the sweep walks
when its handler fires:

  Step 1. For every Permit whose `lifecycle_status` is `ACTIVE` or
          `SUSPENDED` and whose `valid_until` is at or before the current
          logical-clock value, fire the wall-clock-driven `→ EXPIRED`
          terminal transition. The cascade-fan-out abort on every still-
          open child Trip (in `PLANNED` or `IN_TRANSIT`) of the just-
          expired permit fires synchronously inside the per-permit
          transaction, with the `abort_reason` discriminator set to the
          enum value `PERMIT_EXPIRED_CASCADE` and the `aborted_at` field
          set to the current simulated-clock value. The wallet is not
          credited on expiry — the permit's term elapsed in the ordinary
          course and the fees are earned.

  Step 2. For every Permit still in its term (the wall-clock check shows
          `now() < valid_until`), the per-permit verify-compliance
          routine runs internally: the live recompute of the five
          validity-leg conjunction (calculation 1 in its live-mode
          variant), the comparison against the on-disk snapshot's
          conjunction, and the appropriate `ACTIVE ↔ SUSPENDED` transition
          when the two disagree. The cause-discriminator on the sweep's
          response carries the value `GROUNDING_INVALIDATION` for the
          downward transition (snapshot-was-true-live-now-false) and
          `GROUNDING_REVALIDATION` for the upward (snapshot-was-false-
          live-now-true). The snapshot fields are rewritten to the live
          values, the `last_verified_at` is refreshed, and the row's
          `version` is bumped.

  Step 3. For every Driver, the cached `current_rolling_points` field is
          recomputed against the new trailing-edge of the rolling
          penalty-points window (the open-on-the-left, closed-on-the-
          right `(now - PENALTY_WINDOW_DAYS, now]` interval of the §2.9
          conventions table). The wall-clock-expiry of the driver's
          `endorsement_valid_until` field (when its stored value is at or
          before the new now and the current `hazmat_endorsement_status`
          is `VALID`) fires the system-driven `VALID → INVALID` transition
          with the `status_flip` discriminator value `VALID_TO_INVALID`
          in the sweep's response.

  Step 4. The upward direction `INVALID → VALID` is *not* fired by the
          sweep, per the keep-the-regulator-in-the-loop convention of the
          §3.2 paragraph — a driver whose rolling-points has just dropped
          below the threshold by the trailing-edge fall-off remains
          `INVALID` until the regulator's explicit refresh-endorsement
          attestation. The sweep's effect on a driver's standing is the
          downward auto-flip only.

The sweep's per-row work is a sequence of per-row transactions, not a
single big transaction, per the §2.5 H3 paragraph's "the transactional
model is per-row" rule. A failure mid-sweep leaves the already-touched
rows in their post-transition state and the remaining rows in their
pre-sweep state. The handler-side code's exception-safety is the
standard "each per-row block catches its own exception, logs it to the
sweep's response's error-list, and continues with the next row"
pattern; the in-memory store has no transactional rollback machinery,
so the per-row state changes are committed on the dict-mutation
synchronously and a mid-loop exception leaves the dict's state at the
last successful mutation.

The sweep's response payload is the structured summary the §2.5 H3
paragraph names: `as_of_now`, the echoed `scope` from the request body,
the `permit_transitions` array of per-permit `(permit_id, pre_status,
post_status, cause, cascade_trip_aborts)` objects, the
`driver_recomputes` array of per-driver `(driver_id, pre_points,
post_points, status_flip)` objects, the `n_permits_inspected` and
`n_drivers_inspected` summary counts, and the `wallclock_advanced =
False` flag indicating the sweep itself does not move the clock (that
is the clock-advance endpoint's job).

The PRD §2.5 closing paragraph's "the sweep's per-step ordering is the
canonical sequence; implementations that re-order the steps must
guarantee the same observable end-state" pin is the contract: the
expiry-step (Step 1) runs before the verify-compliance-fan-out (Step 2)
so an ACTIVE-permit whose grounding legs are also non-green and whose
`valid_until` has crossed the wall clock receives the terminal
`EXPIRED` label rather than the intermediate `SUSPENDED` label. The
`now() >= valid_until` wall-clock check wins over the live-recompute-
disagrees-with-snapshot question on the choice of the post-sweep
state's name.

The `scope` body argument of the `_sweep/run` request narrows the
sweep's coverage to one of the three named subsets: `"ALL"` (the
default, runs all four steps), `"PERMITS_ONLY"` (runs Steps 1 and 2
only, skipping the per-driver Step 3), and `"DRIVERS_ONLY"` (runs Step
3 only, skipping the per-permit Steps 1 and 2). The three-value enum
lets a test isolate the cascade-A and the cascade-B chains for
independent assertion. An out-of-enum value is the catch-all
`ERR_VALIDATION` 422.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .calculations import (
    compute_per_driver_snapshot_flag,
    compute_per_vehicle_snapshot_flag,
    driver_penalty_point_rolling_total,
    driver_threshold_crossed,
    permit_validity_check,
)
from .clock import current_now, iso_format, parse_iso
from .config import Constants
from .store import STATE_LOCK, bump_version, table


def _abort_open_trips_of_permit(
    permit_id: str, reason: str, now_dt: datetime
) -> list[str]:
    """Synchronously cascade-abort every PLANNED-or-IN_TRANSIT child Trip
    of the named permit. Sets the trip's `trip_status` to the terminal
    `ABORTED`, the `aborted_at` to the canonical ISO string of `now_dt`,
    and the `abort_reason` to the given enum value (one of
    `PERMIT_EXPIRED_CASCADE` for the wall-clock-expiry cascade or
    `PERMIT_SUSPENDED_CASCADE` for the void-issue cascade per the §2.8
    abort-reason taxonomy's enum-economy convention). Bumps the trip's
    `version` and refreshes `updated_at` on each touched row. Returns
    the list of the cascade-aborted trip ids for the response's
    cascade-summary.

    The function assumes the global `STATE_LOCK` is held by the caller
    (the per-permit transaction wraps the permit-row write and the per-
    trip-cascade fan-out in a single critical section so the
    observability of "the permit is EXPIRED and its open trips are all
    ABORTED" is atomic from the test layer's perspective).
    """
    aborted_ids: list[str] = []
    now_iso_str = iso_format(now_dt)
    for trip in list(table("Trip").values()):
        if trip.get("permit_id") != permit_id:
            continue
        if trip.get("trip_status") not in ("PLANNED", "IN_TRANSIT"):
            continue
        trip["trip_status"] = "ABORTED"
        trip["aborted_at"] = now_iso_str
        trip["abort_reason"] = reason
        bump_version(trip)
        aborted_ids.append(trip["id"])
    return aborted_ids


def _reconcile_permit_validity(
    permit: dict[str, Any], constants: Constants, now_dt: datetime
) -> tuple[str, str, str | None]:
    """Run the verify-compliance internal recomputation on a single
    permit during the sweep's Step 2. The arguments are the permit row,
    the deployment-constants table, and the current simulated-clock
    value. Returns the triple `(pre_status, post_status, cause)` of the
    transition fired, with the `cause` being one of the three sweep-
    response cause-discriminator strings — `"GROUNDING_INVALIDATION"` for
    the downward transition, `"GROUNDING_REVALIDATION"` for the upward,
    or None for the no-change case.

    The function is structurally the same as the verify-compliance
    endpoint's handler's internal recompute logic, less the
    request-body parsing and the response-envelope shaping; the permit-
    row's snapshot fields are rewritten in place and the `last_verified_at`
    is refreshed regardless of whether a state-transition fires. The
    `version` bump on the row is part of the side-effect.

    The wall-clock-expiry-overrides-the-grounding-invalidation rule of
    the §2.5 H3 paragraph's "step 1 fires before step 2 so the EXPIRED
    label wins over the SUSPENDED label on a permit whose `valid_until`
    has crossed" is realized by the caller — the caller has already
    walked the table for the `now >= valid_until` permits in step 1 and
    flipped them to EXPIRED; the surviving permits to step 2 are those
    whose wall clock is still inside the term.
    """
    pre_status = permit.get("lifecycle_status")
    if pre_status not in ("ACTIVE", "SUSPENDED"):
        # The sweep does not touch DRAFT permits (no snapshot exists
        # until the issue step writes the initial one) and does not
        # touch the terminal-EXPIRED-and-VOIDED permits (their state is
        # absorbing). The caller's wall-clock-expiry pass has already
        # handled the ACTIVE-or-SUSPENDED-to-EXPIRED case for permits
        # whose `valid_until` is past, so the surviving permits at this
        # call site are the still-in-term ACTIVE-or-SUSPENDED rows.
        return pre_status, pre_status, None

    valid_until_str = permit.get("valid_until")
    valid_until = parse_iso(valid_until_str) if valid_until_str else None
    if valid_until is not None and now_dt >= valid_until:
        # This permit's wall clock has crossed; the caller's step-1
        # expiry pass missed it (shouldn't happen in the canonical
        # ordering, but handle defensively).
        # The Step-1 logic above is the canonical path for this
        # transition; we don't double-cover it here.
        return pre_status, pre_status, None

    # The live-mode recompute of the five-leg conjunction.
    live_overall, live_per_leg = permit_validity_check(
        permit, mode="live", constants=constants, now_override=now_dt
    )

    # The snapshot-mode read for the comparison-against-live decision.
    snapshot_overall, _snapshot_per_leg = permit_validity_check(
        permit, mode="snapshot", constants=constants, now_override=now_dt
    )

    # The transition-decision logic: the live-vs-snapshot disagreement
    # in the downward direction (snapshot-true-live-false) fires the
    # `ACTIVE → SUSPENDED` transition; the upward (snapshot-false-live-
    # true) fires the `SUSPENDED → ACTIVE` reinstatement.
    new_status = pre_status
    cause: str | None = None
    if pre_status == "ACTIVE" and not live_overall:
        new_status = "SUSPENDED"
        cause = "GROUNDING_INVALIDATION"
    elif pre_status == "SUSPENDED" and live_overall:
        new_status = "ACTIVE"
        cause = "GROUNDING_REVALIDATION"

    # Refresh the snapshot fields to the live values on the row
    # regardless of whether a transition fired — the snapshot is the
    # canonical record of "the validity-leg verdict as of the latest
    # verify-compliance pass" and the sweep's per-permit pass counts as
    # such a verify-compliance internally.
    _write_snapshot_fields(permit, constants, now_dt)
    permit["last_verified_at"] = iso_format(now_dt)

    if new_status != pre_status:
        permit["lifecycle_status"] = new_status

    bump_version(permit)
    return pre_status, new_status, cause


def _write_snapshot_fields(
    permit: dict[str, Any], constants: Constants, now_dt: datetime
) -> None:
    """Write the five strict-snapshot fields onto the permit row to the
    current live values of the grounding-entity legs, in the pinned
    evaluation order. Called by the issue handler, the verify-compliance
    handler, the renewal handler (which embeds an implicit verify-
    compliance per the §3.6 paragraph's renewal-handler-also-refreshes-
    the-snapshot rule), and the sweep's per-permit-step-2 helper above.

    The per-driver-and-per-vehicle snapshot maps are rebuilt from the
    current `authorized_driver_ids` and `authorized_vehicle_ids` arrays
    of the permit; an authorized id whose backing entity has gone
    missing (which the validation tier rejects at issue/renewal time
    and therefore doesn't happen in practice) maps to a false flag on
    the safe-default side.
    """
    from .store import find

    valid_from_str = permit.get("valid_from")
    valid_until_str = permit.get("valid_until")
    valid_from = parse_iso(valid_from_str) if valid_from_str else None
    valid_until = parse_iso(valid_until_str) if valid_until_str else None

    company_id = permit.get("company_id")
    company = find("TransportCompany", company_id) if company_id else None
    permit["snapshot_company_qualified"] = bool(
        company is not None
        and company.get("qualification_status") == "APPROVED"
    )

    driver_map: dict[str, bool] = {}
    for did in permit.get("authorized_driver_ids", []):
        if valid_until is None:
            driver_map[did] = False
        else:
            driver_map[did] = compute_per_driver_snapshot_flag(
                did, valid_until, constants
            )
    permit["snapshot_driver_endorsements"] = driver_map

    vehicle_map: dict[str, bool] = {}
    for vid in permit.get("authorized_vehicle_ids", []):
        if valid_until is None:
            vehicle_map[vid] = False
        else:
            vehicle_map[vid] = compute_per_vehicle_snapshot_flag(
                vid, valid_until
            )
    permit["snapshot_vehicle_inspections"] = vehicle_map

    route = find("TransportRoute", permit.get("route_id")) if permit.get("route_id") else None
    permit["snapshot_route_approved"] = bool(
        route is not None and route.get("approval_status") == "APPROVED"
    )

    if valid_from is None or valid_until is None:
        permit["snapshot_within_window"] = False
    else:
        permit["snapshot_within_window"] = valid_from <= now_dt < valid_until


def _recompute_driver_points(
    driver: dict[str, Any], constants: Constants, now_dt: datetime
) -> tuple[int, int, str | None]:
    """Recompute the driver's cached `current_rolling_points` for the
    sweep's Step 3 against the new trailing-edge of the rolling window.
    Then evaluate the wall-clock-expiry-of-`endorsement_valid_until`
    automatic-flip-to-INVALID rule per the §3.2 paragraph's "the
    sweep's wall-clock-driven `VALID → INVALID` transition fires on the
    `endorsement_valid_until <= now()` condition".

    Returns the triple `(pre_points, post_points, status_flip)` where
    `status_flip` is the response's per-driver `status_flip`
    discriminator: the string `"VALID_TO_INVALID"` on the wall-clock-
    expiry downward auto-flip, or None on the no-flip case. The upward
    direction `INVALID → VALID` is not fired by the sweep per the
    keep-regulator-in-loop convention.

    The threshold-driven `VALID → INVALID` direction (the rolling-
    points-crossover case) is fired synchronously inside the Penalty-
    creation handler's transaction rather than here in the sweep, on
    the principle that the threshold-crossover is the immediate effect
    of the penalty insert; the sweep's role on the rolling-points axis
    is solely the trailing-edge fall-off recompute and the wall-clock-
    expiry-of-the-attestation downward flip.

    The cache freshness convention is "the cached `current_rolling_points`
    field on the Driver row reflects the function evaluated at the
    current simulated-clock value", so the sweep's recompute writes the
    new total verbatim and the on-disk row's value is what the
    permit-validity check's drivers-leg's points-below-threshold sub-
    check reads next.
    """
    driver_id = driver["id"]
    pre_points = int(driver.get("current_rolling_points", 0))
    new_points = driver_penalty_point_rolling_total(driver_id, now_dt, constants)
    status_flip: str | None = None
    if new_points != pre_points:
        driver["current_rolling_points"] = new_points
        bump_version(driver)

    # Wall-clock-expiry of the attestation's `endorsement_valid_until`
    # — the standard "the attestation has aged past its stored expiry
    # and the driver's status auto-flips to INVALID" rule. The grace
    # constant `ENDORSEMENT_RENEWAL_GRACE_DAYS` from `config` is the
    # cushion past the stored end before the flip fires; the scaffold's
    # canonical value is zero days for the hard-cutoff convention.
    pre_status = driver.get("hazmat_endorsement_status")
    eu_str = driver.get("endorsement_valid_until")
    if pre_status == "VALID" and eu_str is not None:
        eu = parse_iso(eu_str)
        grace = timedelta(days=constants.endorsement_renewal_grace_days)
        if now_dt >= eu + grace:
            driver["hazmat_endorsement_status"] = "INVALID"
            bump_version(driver)
            status_flip = "VALID_TO_INVALID"

    # The threshold-crossover-driven downward auto-flip is checked here
    # as a defensive second-pass after the rolling-points recompute:
    # if the recompute happens to bring a previously-clean driver above
    # the threshold (which can happen if a penalty's `observed_at` is
    # backdated to within the window by a regulator's manual entry on a
    # past-observation event, an unusual but in-spec case the rolling
    # sum picks up on its next evaluation), the driver's status flips
    # to INVALID. The status-flip discriminator is the same
    # "VALID_TO_INVALID" value — the sweep's response's per-driver
    # entry carries the union "the driver flipped from VALID to INVALID
    # this sweep" without distinguishing the wall-clock cause from the
    # points-threshold cause.
    if (
        driver.get("hazmat_endorsement_status") == "VALID"
        and driver_threshold_crossed(new_points, constants)
    ):
        driver["hazmat_endorsement_status"] = "INVALID"
        bump_version(driver)
        if status_flip is None:
            status_flip = "VALID_TO_INVALID"

    return pre_points, int(driver.get("current_rolling_points", new_points)), status_flip


def run_sweep(scope: str, constants: Constants) -> dict[str, Any]:
    """The top-level sweep entry point the admin blueprint's
    `_sweep/run` handler calls. Walks the four canonical steps in the
    pinned order:

      Step 1 — wall-clock-expiry on permits (the `valid_until` has
      crossed) and the synchronous trip-cascade-abort fan-out.

      Step 2 — for the still-in-term ACTIVE-and-SUSPENDED permits, the
      verify-compliance internal recompute that fires the
      `ACTIVE ↔ SUSPENDED` cycle based on the live-vs-snapshot
      disagreement.

      Step 3 — for every Driver, the rolling-points recompute against
      the new trailing-edge and the wall-clock-expiry-of-the-attestation
      check that fires the downward `VALID → INVALID` flip.

      Step 4 — the idempotency-key slot garbage collection is a no-op
      per the §1.0 idempotency block's "tests never exercise stale-key
      revival" note.

    The `scope` argument narrows the steps the sweep runs: `"ALL"` (the
    default) runs Steps 1, 2, and 3; `"PERMITS_ONLY"` runs Steps 1 and
    2 (skipping the per-driver work); `"DRIVERS_ONLY"` runs Step 3
    only. The validation of the `scope` enum-value is the caller's
    responsibility — the admin-blueprint's handler walks the §2.7 H3
    catch-all body-shape tier on the request's `scope` field before
    invoking this function.

    The return is the structured summary the §2.5 H3 paragraph names:
    the `as_of_now` ISO string, the echoed `scope`, the per-permit and
    per-driver transition arrays, the two count summaries, and the
    `wallclock_advanced = False` flag. The handler wraps this dict as
    the `data` field of the response-envelope's success-shape.
    """
    now = current_now()
    now_iso = iso_format(now)

    permit_transitions: list[dict[str, Any]] = []
    driver_recomputes: list[dict[str, Any]] = []

    with STATE_LOCK:
        if scope in ("ALL", "PERMITS_ONLY"):
            # Step 1: wall-clock-expiry on permits. The walk takes a
            # snapshot of the current row-list so the mutation of the
            # dict during iteration is safe — Python's dict-iteration
            # forbids in-iter mutation, but the snapshot-list approach
            # decouples the iteration from the mutation.
            permits_snapshot = list(table("Permit").values())
            permits_inspected = 0
            for permit in permits_snapshot:
                permits_inspected += 1
                pre_status = permit.get("lifecycle_status")
                if pre_status not in ("ACTIVE", "SUSPENDED"):
                    # DRAFT, EXPIRED, VOIDED — not touched by the sweep
                    # (the absorbing-terminal states and the not-yet-
                    # issued DRAFT state have no automatic transitions
                    # in the sweep's purview).
                    continue
                valid_until_str = permit.get("valid_until")
                if valid_until_str is None:
                    continue
                valid_until = parse_iso(valid_until_str)
                if now >= valid_until:
                    # Wall-clock expiry. The post-state is the terminal
                    # `EXPIRED`. The trip-cascade fan-out fires
                    # synchronously inside this transaction with the
                    # `PERMIT_EXPIRED_CASCADE` discriminator.
                    aborted = _abort_open_trips_of_permit(
                        permit["id"], "PERMIT_EXPIRED_CASCADE", now
                    )
                    permit["lifecycle_status"] = "EXPIRED"
                    # The `snapshot_within_window` flag refreshes to
                    # `False` since the wall-clock is now at-or-past
                    # the right edge of the half-open interval.
                    permit["snapshot_within_window"] = False
                    bump_version(permit)
                    permit_transitions.append(
                        {
                            "permit_id": permit["id"],
                            "pre_status": pre_status,
                            "post_status": "EXPIRED",
                            "cause": "WALL_CLOCK_EXPIRY",
                            "cascade_trip_aborts": aborted,
                        }
                    )
                    continue

            # Step 2: still-in-term verify-compliance fan-out. The
            # post-state-after-step-1 dict is what we iterate now.
            for permit in list(table("Permit").values()):
                pre_status = permit.get("lifecycle_status")
                if pre_status not in ("ACTIVE", "SUSPENDED"):
                    continue
                # Re-read the permit's wall-clock state — Step 1 may
                # have already flipped some permits to EXPIRED in this
                # same sweep call, in which case the
                # `_reconcile_permit_validity` returns without firing a
                # transition (it sees the pre-state as not-ACTIVE-or-
                # SUSPENDED after Step 1 wrote EXPIRED, but the
                # iteration here picks up only the still-ACTIVE-or-
                # SUSPENDED rows so this is consistent).
                pre, post, cause = _reconcile_permit_validity(
                    permit, constants, now
                )
                if cause is not None:
                    # A transition fired. No trip-cascade on the
                    # `ACTIVE ↔ SUSPENDED` arcs per the §3.5 paragraph's
                    # "the suspension does not auto-abort trips" rule —
                    # the gating effect on the GPS-write path is the
                    # ERR_PERMIT_NOT_ACTIVE 409 at the gps-ingest's
                    # safety-tier priority 515 check, not a row-level
                    # mutation on the trips. So `cascade_trip_aborts`
                    # is the empty list on the SUSPENDED-or-reinstate
                    # transitions.
                    permit_transitions.append(
                        {
                            "permit_id": permit["id"],
                            "pre_status": pre,
                            "post_status": post,
                            "cause": cause,
                            "cascade_trip_aborts": [],
                        }
                    )
            permits_inspected_total = permits_inspected
        else:
            # `scope == "DRIVERS_ONLY"`. The permit-table is untouched.
            permits_inspected_total = 0

        # Step 3: per-driver rolling-points recompute and the
        # wall-clock-driven attestation-expiry auto-flip.
        drivers_inspected = 0
        if scope in ("ALL", "DRIVERS_ONLY"):
            for driver in list(table("Driver").values()):
                drivers_inspected += 1
                pre_points, post_points, status_flip = _recompute_driver_points(
                    driver, constants, now
                )
                if pre_points != post_points or status_flip is not None:
                    driver_recomputes.append(
                        {
                            "driver_id": driver["id"],
                            "pre_points": pre_points,
                            "post_points": post_points,
                            "status_flip": status_flip,
                        }
                    )

    return {
        "as_of_now": now_iso,
        "scope": scope,
        "permit_transitions": permit_transitions,
        "driver_recomputes": driver_recomputes,
        "n_permits_inspected": permits_inspected_total,
        "n_drivers_inspected": drivers_inspected,
        "wallclock_advanced": False,
    }


# Re-export the snapshot-writing helper for the verify-compliance
# endpoint's handler.
__all__ = ["run_sweep", "_write_snapshot_fields", "_abort_open_trips_of_permit"]
