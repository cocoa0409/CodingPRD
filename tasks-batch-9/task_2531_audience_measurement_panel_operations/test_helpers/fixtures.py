"""Composite fixtures that build multi-step preconditions.

The harness kills and relaunches the API server before every individual test, so
every test opens against an empty store and a logical clock reading
``2026-08-01T00:00:00Z``. Every precondition in this module is therefore built
from scratch through the PRD's own endpoints; nothing here reaches around the API.

The workhorse is :class:`PanelHarness`, an orchestration layer over ``ApiClient``
exposing one method per recurring setup chain -- register a market, arm a quota
cell, publish a universe vintage and a rule set, recruit a household and drive it
into tab, ingest measured blocks, open and edit and weight and publish a run,
subscribe a client, and open the governance objects.

The canonical measurement timeline every composite uses:

* ``2026-08-01T00:00:00Z`` -- the startup clock. Market, cells, rule set and
  universe vintage are created here; households are recruited and enumerated
  here, so a first enumeration is 0 days old and always timely.
* ``2026-08-02T00:00:00Z`` -- the clock is advanced here before any interval is
  ingested, because ``end_iso`` must be at or before the clock and a run's
  ``window_end_iso`` must be too. Measured blocks therefore sit inside
  ``2026-08-01T00:00:00Z`` to ``2026-08-02T00:00:00Z``, a 1440-minute window.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient, api_client
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.factories import (
    accreditation_audit_payload,
    cell_population,
    client_payload,
    custom_analysis_payload,
    edit_rule_set_payload,
    enumeration_payload,
    finalize_audit_payload,
    household_payload,
    market_payload,
    methodology_change_payload,
    meter_payload,
    next_serial_no,
    processing_run_payload,
    quota_cell_payload,
    scheduled_deliverable_payload,
    tuning_interval_payload,
    universe_estimate_payload,
)
from test_helpers.test_users import (
    AUDITOR_FINALIZER_USER_ID,
    AUDITOR_USER_ID,
    CLIENT_SERVICE_USER_ID,
    DIRECTOR_ACTIVATOR_USER_ID,
    DIRECTOR_USER_ID,
    FIELD_TECH_USER_ID,
    PANEL_OPS_USER_ID,
    STATISTICIAN_PUBLISHER_USER_ID,
    STATISTICIAN_USER_ID,
    make_auditor_headers,
    make_client_service_headers,
    make_client_user_headers,
    make_director_headers,
    make_field_tech_headers,
    make_panel_ops_headers,
    make_statistician_headers,
)

# The canonical timeline. `WINDOW_MINUTES` is the run's own `window_minutes`.
CLOCK_T0 = "2026-08-01T00:00:00Z"
CLOCK_T1 = "2026-08-02T00:00:00Z"
WINDOW_START = "2026-08-01T00:00:00Z"
WINDOW_END = "2026-08-02T00:00:00Z"
WINDOW_MINUTES = 1440
VINTAGE_FROM = "2026-07-01T00:00:00Z"
VINTAGE_TO = "2026-10-01T00:00:00Z"


class PanelHarness:
    """Setup orchestration over the audience measurement panel API."""

    def __init__(self, client: ApiClient):
        self.client = client
        self.ops = make_panel_ops_headers()
        self.tech = make_field_tech_headers()
        self.statistician = make_statistician_headers(STATISTICIAN_USER_ID)
        self.publisher = make_statistician_headers(STATISTICIAN_PUBLISHER_USER_ID)
        self.rep = make_client_service_headers()
        self.auditor = make_auditor_headers(AUDITOR_USER_ID)
        self.finalizer = make_auditor_headers(AUDITOR_FINALIZER_USER_ID)
        self.director = make_director_headers(DIRECTOR_USER_ID)
        self.activator = make_director_headers(DIRECTOR_ACTIVATOR_USER_ID)

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str) -> str:
        """Move the logical clock forward and return the newly effective instant."""
        data = validate_success(self.client.set_logical_clock(self.ops, current_utc=current_utc), 200)
        return data["current_utc"]

    # ------------------------------------------------------------------
    # Markets and quota cells (PRD 3.1)
    # ------------------------------------------------------------------

    def create_market(self, **overrides) -> Dict[str, Any]:
        """Register one market; posture lands at RESTRICTED with no cells yet."""
        headers = overrides.pop("headers", self.ops)
        return get_success_data(self.client.create_market(headers, **market_payload(**overrides)))

    def market_version(self, market_id: str) -> int:
        """Read the market's current `version` for an optimistic-concurrency pin."""
        return get_success_data(self.client.get_market(self.ops, market_id))["version"]

    def read_market(self, market_id: str) -> Dict[str, Any]:
        """Re-read a market so a test can inspect its roll-ups and posture."""
        return get_success_data(self.client.get_market(self.ops, market_id))

    def create_quota_cell(self, market_id: str, **overrides) -> Dict[str, Any]:
        """Add one stratum; it lands UNDER_TARGET with its boost armed at 1.25."""
        headers = overrides.pop("headers", self.ops)
        return get_success_data(
            self.client.create_quota_cell(headers, market_id, **quota_cell_payload(**overrides))
        )

    def read_quota_cell(self, quota_cell_id: str) -> Dict[str, Any]:
        """Re-read a cell so a test can inspect its fill grade and boost."""
        return get_success_data(self.client.get_quota_cell(self.ops, quota_cell_id))

    def market_with_cells(
        self, cell_specs: Optional[Sequence[Dict[str, Any]]] = None, **market_overrides
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """A market plus one cell per spec, created in the order given."""
        market = self.create_market(**market_overrides)
        specs = list(cell_specs) if cell_specs is not None else [{}]
        cells = [self.create_quota_cell(market["id"], **spec) for spec in specs]
        return market, cells

    # ------------------------------------------------------------------
    # Editing rule sets and universe vintages (PRD 3.5)
    # ------------------------------------------------------------------

    def draft_rule_set(self, **overrides) -> Dict[str, Any]:
        """Draft a rule set and leave it in DRAFT."""
        headers = overrides.pop("headers", self.statistician)
        return get_success_data(
            self.client.create_edit_rule_set(headers, **edit_rule_set_payload(**overrides))
        )

    def published_rule_set(self, **overrides) -> Dict[str, Any]:
        """Draft and publish a rule set; returns the PUBLISHED row."""
        headers = overrides.pop("headers", self.statistician)
        draft = self.draft_rule_set(headers=headers, **overrides)
        return validate_success(self.client.publish_edit_rule_set(headers, draft["id"]), 200)

    def read_rule_set(self, edit_rule_set_id: str) -> Dict[str, Any]:
        """Re-read a rule set to inspect its status and thresholds."""
        return get_success_data(self.client.get_edit_rule_set(self.statistician, edit_rule_set_id))

    def draft_universe(
        self, market_id: str, quota_cell_ids: Sequence[str], **overrides
    ) -> Dict[str, Any]:
        """Draft a vintage covering exactly the named cells; leaves it DRAFT."""
        headers = overrides.pop("headers", self.statistician)
        populations = overrides.pop(
            "cell_populations", [cell_population(cell_id) for cell_id in quota_cell_ids]
        )
        version = overrides.pop("expected_market_version", None)
        if version is None:
            version = self.market_version(market_id)
        overrides.setdefault("effective_from", VINTAGE_FROM)
        overrides.setdefault("effective_to", VINTAGE_TO)
        return get_success_data(
            self.client.create_universe_estimate(
                headers,
                **universe_estimate_payload(
                    market_id, version, populations, **overrides
                ),
            )
        )

    def published_universe(
        self, market_id: str, quota_cell_ids: Sequence[str], **overrides
    ) -> Dict[str, Any]:
        """Draft and publish a vintage; returns the PUBLISHED row."""
        headers = overrides.pop("headers", self.statistician)
        draft = self.draft_universe(market_id, quota_cell_ids, headers=headers, **overrides)
        return validate_success(self.client.publish_universe_estimate(headers, draft["id"]), 200)

    def read_universe(self, universe_estimate_id: str) -> Dict[str, Any]:
        """Re-read a vintage to inspect its status and totals."""
        return get_success_data(
            self.client.get_universe_estimate(self.statistician, universe_estimate_id)
        )

    # ------------------------------------------------------------------
    # Households, meters and enumeration (PRD 3.2, 3.3)
    # ------------------------------------------------------------------

    def recruit_household(self, market_id: str, quota_cell_id: str, **overrides) -> Dict[str, Any]:
        """Recruit one home; it lands RECRUITED and is not yet in tab."""
        headers = overrides.pop("headers", self.ops)
        return get_success_data(
            self.client.create_household(
                headers, **household_payload(market_id, quota_cell_id, **overrides)
            )
        )

    def read_household(self, household_id: str) -> Dict[str, Any]:
        """Re-read a household to inspect its status, verdict and ledger."""
        return get_success_data(self.client.get_household(self.ops, household_id))

    def ship_meter(self, household_id: str, **overrides) -> Dict[str, Any]:
        """Ship one device; a first shipment moves a RECRUITED home to INSTALL_SCHEDULED."""
        headers = overrides.pop("headers", self.tech)
        return get_success_data(
            self.client.create_meter(headers, **meter_payload(household_id, **overrides))
        )

    def install_meter(self, meter_id: str, **overrides) -> Dict[str, Any]:
        """Confirm a physical install; a TV_TUNER moves the home to ENUM_PENDING."""
        headers = overrides.pop("headers", self.tech)
        return validate_success(self.client.confirm_meter_install(headers, meter_id), 200)

    def installed_meter(self, household_id: str, **overrides) -> Dict[str, Any]:
        """Ship and confirm one device in a single step; returns the INSTALLED row."""
        headers = overrides.pop("headers", self.tech)
        meter = self.ship_meter(household_id, headers=headers, **overrides)
        return self.install_meter(meter["id"], headers=headers)

    def read_meter(self, meter_id: str) -> Dict[str, Any]:
        """Re-read a meter to inspect both of its independent status dimensions."""
        return get_success_data(self.client.get_meter(self.tech, meter_id))

    def enumerate_household(self, household_id: str, **overrides) -> Dict[str, Any]:
        """Record one enumeration visit; returns the refreshed household row."""
        headers = overrides.pop("headers", self.tech)
        return get_success_data(
            self.client.create_enumeration(
                headers, household_id, **enumeration_payload(**overrides)
            )
        )

    def active_household(
        self,
        market_id: str,
        quota_cell_id: str,
        persons_count: int = 3,
        extra_meter_types: Sequence[str] = (),
        **overrides,
    ) -> Dict[str, Any]:
        """Recruit, meter, install and enumerate one home all the way into tab.

        Returns a dict of ``household``, ``tuner`` and ``meters``. The enumeration
        submits a roster equal to `persons_count` and one television set, so all
        three verdict tests pass and the home lands ACTIVE.

        Every device is shipped before any is confirmed, because PRD 3.3 shipping
        check 1 admits only a `RECRUITED` or `INSTALL_SCHEDULED` household and
        confirming the tuner moves the home straight to `ENUM_PENDING`.
        """
        household = self.recruit_household(
            market_id, quota_cell_id, persons_count=persons_count, **overrides
        )
        shipped = [self.ship_meter(household["id"], meter_type="TV_TUNER")]
        for meter_type in extra_meter_types:
            shipped.append(self.ship_meter(household["id"], meter_type=meter_type))
        meters = [self.install_meter(meter["id"]) for meter in shipped]
        tuner = meters[0]
        household = self.enumerate_household(
            household["id"], roster_persons_count=persons_count, tv_sets_count=1
        )
        return {"household": household, "tuner": tuner, "meters": meters}

    # ------------------------------------------------------------------
    # Tuning interval ingest (PRD 3.6)
    # ------------------------------------------------------------------

    def ingest_interval(
        self,
        meter_id: str,
        household_id: str,
        start_iso: str,
        end_iso: str,
        tuning_minutes: int,
        **overrides,
    ) -> Dict[str, Any]:
        """Ingest one measured block; it lands RAW with `usable_minutes` 0."""
        headers = overrides.pop("headers", self.statistician)
        return get_success_data(
            self.client.create_tuning_interval(
                headers,
                **tuning_interval_payload(
                    meter_id, household_id, start_iso, end_iso, tuning_minutes, **overrides
                ),
            )
        )

    def read_interval(self, tuning_interval_id: str) -> Dict[str, Any]:
        """Re-read one block to inspect its state and credited minutes."""
        return get_success_data(
            self.client.get_tuning_interval(self.statistician, tuning_interval_id)
        )

    def intervals_of_run(self, processing_run_id: str, **params) -> List[Dict[str, Any]]:
        """Every block claimed by a run, as one page of up to 100 rows."""
        params.setdefault("limit", 100)
        response = self.client.list_tuning_intervals(
            self.statistician, processing_run_id=processing_run_id, **params
        )
        return validate_success(response, 200)

    def intervals_of_meter(self, meter_id: str, **params) -> List[Dict[str, Any]]:
        """Every block of one device, in the collection's own `start_iso` order."""
        params.setdefault("limit", 100)
        response = self.client.list_tuning_intervals(self.statistician, meter_id=meter_id, **params)
        return validate_success(response, 200)

    # ------------------------------------------------------------------
    # Processing runs (PRD 3.6, 3.7)
    # ------------------------------------------------------------------

    def open_run(
        self,
        market_id: str,
        universe_estimate_id: str,
        edit_rule_set_id: str,
        **overrides,
    ) -> Dict[str, Any]:
        """Open one run; it lands OPEN with `intab_snapshot_count` frozen."""
        headers = overrides.pop("headers", self.statistician)
        version = overrides.pop("expected_market_version", None)
        if version is None:
            version = self.market_version(market_id)
        overrides.setdefault("window_start_iso", WINDOW_START)
        overrides.setdefault("window_end_iso", WINDOW_END)
        return get_success_data(
            self.client.create_processing_run(
                headers,
                **processing_run_payload(
                    market_id, universe_estimate_id, edit_rule_set_id, version, **overrides
                ),
            )
        )

    def edit_run(self, processing_run_id: str, **overrides) -> Dict[str, Any]:
        """Run the seven-step editing pass; the run moves OPEN to EDITED."""
        headers = overrides.pop("headers", self.statistician)
        return validate_success(self.client.edit_processing_run(headers, processing_run_id), 200)

    def weight_run(self, processing_run_id: str, weight_variant: str = "FINAL", **overrides):
        """Run the weighting pass under one variant; the run moves to WEIGHTED."""
        headers = overrides.pop("headers", self.statistician)
        return validate_success(
            self.client.weight_processing_run(
                headers, processing_run_id, weight_variant=weight_variant
            ),
            200,
        )

    def publish_run(self, processing_run_id: str, **overrides) -> Dict[str, Any]:
        """Publish a WEIGHTED run under a publisher distinct from its opener."""
        headers = overrides.pop("headers", self.publisher)
        return validate_success(self.client.publish_processing_run(headers, processing_run_id), 200)

    def read_run(self, processing_run_id: str) -> Dict[str, Any]:
        """Re-read a run to inspect its tallies, mass and disclosures."""
        return get_success_data(
            self.client.get_processing_run(self.statistician, processing_run_id)
        )

    def weights_of_run(self, processing_run_id: str, **params) -> List[Dict[str, Any]]:
        """Every household weight row of a run, in `created_at` ascending order."""
        params.setdefault("limit", 100)
        response = self.client.list_household_weights(
            self.statistician, processing_run_id=processing_run_id, **params
        )
        return validate_success(response, 200)

    # ------------------------------------------------------------------
    # The canonical measurement chain
    # ------------------------------------------------------------------

    def measurement_base(
        self,
        cell_specs: Optional[Sequence[Dict[str, Any]]] = None,
        rule_set: Optional[Dict[str, Any]] = None,
        **rule_set_overrides,
    ) -> Dict[str, Any]:
        """A market with cells, a PUBLISHED rule set and a PUBLISHED vintage.

        Returns ``market``, ``cells``, ``rule_set`` and ``universe``. Nothing is
        recruited yet, so a caller is free to build whatever panel it needs.
        """
        market, cells = self.market_with_cells(cell_specs)
        if rule_set is None:
            rule_set = self.published_rule_set(**rule_set_overrides)
        universe = self.published_universe(market["id"], [cell["id"] for cell in cells])
        return {"market": market, "cells": cells, "rule_set": rule_set, "universe": universe}

    def panel_with_data(
        self,
        household_specs: Optional[Sequence[Dict[str, Any]]] = None,
        cell_specs: Optional[Sequence[Dict[str, Any]]] = None,
        **base_overrides,
    ) -> Dict[str, Any]:
        """The full chain up to ingested data, with the clock advanced to T1.

        Each entry of ``household_specs`` may carry ``cell_index`` (default 0),
        ``persons_count`` (default 3), ``extra_meter_types`` (default none) and
        ``intervals``, a list of ``(start_iso, end_iso, tuning_minutes)`` triples
        or of keyword dicts passed straight to :meth:`ingest_interval`.

        Returns the ``measurement_base`` keys plus ``households`` (one dict per
        spec, as :meth:`active_household` returns) and ``intervals``.
        """
        base = self.measurement_base(cell_specs=cell_specs, **base_overrides)
        specs = list(household_specs) if household_specs is not None else [{}]
        households: List[Dict[str, Any]] = []
        for spec in specs:
            cell = base["cells"][spec.get("cell_index", 0)]
            households.append(
                self.active_household(
                    base["market"]["id"],
                    cell["id"],
                    persons_count=spec.get("persons_count", 3),
                    extra_meter_types=spec.get("extra_meter_types", ()),
                )
            )
        self.set_clock(CLOCK_T1)
        intervals: List[Dict[str, Any]] = []
        for spec, built in zip(specs, households):
            for block in spec.get("intervals", []):
                if isinstance(block, dict):
                    kwargs = dict(block)
                    meter_id = kwargs.pop("meter_id", built["tuner"]["id"])
                    intervals.append(
                        self.ingest_interval(
                            meter_id, built["household"]["id"], **kwargs
                        )
                    )
                else:
                    start_iso, end_iso, tuning_minutes = block
                    intervals.append(
                        self.ingest_interval(
                            built["tuner"]["id"],
                            built["household"]["id"],
                            start_iso,
                            end_iso,
                            tuning_minutes,
                        )
                    )
        base["households"] = households
        base["intervals"] = intervals
        return base

    def open_run_over(self, base: Dict[str, Any], **overrides) -> Dict[str, Any]:
        """Open a run over the whole canonical window of an existing base."""
        return self.open_run(
            base["market"]["id"],
            base["universe"]["id"],
            base["rule_set"]["id"],
            **overrides,
        )

    def edited_run(self, **kwargs) -> Dict[str, Any]:
        """A base, a panel with one 600-minute block each, and an EDITED run."""
        base = kwargs.pop("base", None)
        if base is None:
            base = self.panel_with_data(
                household_specs=kwargs.pop(
                    "household_specs",
                    [{"intervals": [(WINDOW_START, "2026-08-01T10:00:00Z", 600)]}],
                ),
                **kwargs,
            )
        run = self.open_run_over(base)
        base["run"] = self.edit_run(run["id"])
        return base

    def weighted_run(self, weight_variant: str = "FINAL", **kwargs) -> Dict[str, Any]:
        """The same chain carried one step further into WEIGHTED."""
        base = self.edited_run(**kwargs)
        base["run"] = self.weight_run(base["run"]["id"], weight_variant=weight_variant)
        return base

    def published_run(self, weight_variant: str = "FINAL", **kwargs) -> Dict[str, Any]:
        """The same chain carried all the way to a terminal PUBLISHED run."""
        base = self.weighted_run(weight_variant=weight_variant, **kwargs)
        base["run"] = self.publish_run(base["run"]["id"])
        return base

    # ------------------------------------------------------------------
    # Cooperation incentives (PRD 3.4)
    # ------------------------------------------------------------------

    def accrue(self, household_id: str, period_label: str = "2026-08", **overrides):
        """Accrue one payment period against a household."""
        headers = overrides.pop("headers", self.ops)
        return validate_success(
            self.client.accrue_incentive(headers, household_id, period_label=period_label), 200
        )

    def reverse(
        self,
        household_id: str,
        period_label: str = "2026-08",
        memo: str = "Audit found the compliance figure used was wrong.",
        **overrides,
    ):
        """Reverse a period, leaving the ledger entry in place with `reversed` true."""
        headers = overrides.pop("headers", self.ops)
        return validate_success(
            self.client.reverse_accrual(headers, household_id, period_label=period_label, memo=memo),
            200,
        )

    # ------------------------------------------------------------------
    # Clients and deliverables (PRD 3.8)
    # ------------------------------------------------------------------

    def create_client(self, contract_market_ids: Sequence[str], **overrides) -> Dict[str, Any]:
        """Register one subscriber; the tier fixes all three commercial fields."""
        headers = overrides.pop("headers", self.rep)
        return get_success_data(
            self.client.create_client(headers, **client_payload(list(contract_market_ids), **overrides))
        )

    def client_headers(self, client_id: str) -> Dict[str, str]:
        """`ClientUser` headers whose `X-User-ID` is the Client row's own id."""
        return make_client_user_headers(client_id)

    def read_client(self, client_id: str) -> Dict[str, Any]:
        """Re-read a subscriber to inspect its counters and credit."""
        return get_success_data(self.client.get_client(self.rep, client_id))

    def schedule_deliverable(
        self, client_id: str, processing_run_id: str, **overrides
    ) -> Dict[str, Any]:
        """Place a dataset delivery on a client's schedule; it lands SCHEDULED."""
        headers = overrides.pop("headers", self.rep)
        return get_success_data(
            self.client.create_scheduled_deliverable(
                headers,
                client_id,
                **scheduled_deliverable_payload(processing_run_id, **overrides),
            )
        )

    def request_custom_analysis(
        self, client_id: str, processing_run_id: str, **overrides
    ) -> Dict[str, Any]:
        """File a bespoke question against published data; it lands REQUESTED."""
        headers = overrides.pop("headers", self.rep)
        return get_success_data(
            self.client.create_custom_analysis(
                headers,
                **custom_analysis_payload(client_id, processing_run_id, **overrides),
            )
        )

    def read_deliverable(self, client_deliverable_id: str) -> Dict[str, Any]:
        """Re-read a deliverable to inspect its state, hold and pricing."""
        return get_success_data(
            self.client.get_client_deliverable(self.rep, client_deliverable_id)
        )

    def delivered_custom_analysis(
        self, client_id: str, processing_run_id: str, **overrides
    ) -> Dict[str, Any]:
        """Walk branch B all the way: REQUESTED to IN_PROGRESS to DELIVERED."""
        findings = overrides.pop(
            "findings_summary", "Suburban cells carried the week-over-week lift."
        )
        row = self.request_custom_analysis(client_id, processing_run_id, **overrides)
        validate_success(self.client.start_deliverable(self.rep, row["id"]), 200)
        return validate_success(
            self.client.deliver_deliverable(self.rep, row["id"], findings_summary=findings), 200
        )

    def subscribed_published_run(
        self, tier: str = "STANDARD", **kwargs
    ) -> Dict[str, Any]:
        """A PUBLISHED run plus a client contracted to that run's market.

        Returns the :meth:`published_run` keys plus ``client``.
        """
        base = self.published_run(**kwargs)
        base["client"] = self.create_client([base["market"]["id"]], tier=tier)
        return base

    # ------------------------------------------------------------------
    # Methodology change governance (PRD 3.9)
    # ------------------------------------------------------------------

    def draft_change(
        self,
        target_edit_rule_set_id: str,
        proposed_edit_rule_set_id: str,
        affected_market_ids: Sequence[str],
        **overrides,
    ) -> Dict[str, Any]:
        """Open a change in DRAFT with `created_by_user_id` stamped."""
        headers = overrides.pop("headers", self.director)
        return get_success_data(
            self.client.create_methodology_change(
                headers,
                **methodology_change_payload(
                    target_edit_rule_set_id,
                    proposed_edit_rule_set_id,
                    list(affected_market_ids),
                    **overrides,
                ),
            )
        )

    def assess_change(
        self, methodology_change_id: str, baseline_processing_run_id: str, **overrides
    ) -> Dict[str, Any]:
        """Score a DRAFT change against a PUBLISHED baseline run."""
        headers = overrides.pop("headers", self.director)
        version = overrides.pop("expected_methodology_change_version", None)
        if version is None:
            version = self.read_change(methodology_change_id)["version"]
        return get_success_data(
            self.client.create_impact_analysis(
                headers,
                methodology_change_id,
                baseline_processing_run_id=baseline_processing_run_id,
                expected_methodology_change_version=version,
            )
        )

    def notify_change(self, methodology_change_id: str, **overrides) -> Dict[str, Any]:
        """Fan the disclosure out to every affected subscriber."""
        headers = overrides.pop("headers", self.director)
        return validate_success(
            self.client.notify_methodology_change(headers, methodology_change_id), 200
        )

    def read_change(self, methodology_change_id: str) -> Dict[str, Any]:
        """Re-read a change to inspect its state, score and counters."""
        return get_success_data(
            self.client.get_methodology_change(self.director, methodology_change_id)
        )

    def notifications_of_change(self, methodology_change_id: str, **params) -> List[Dict[str, Any]]:
        """Every notification row of a change, in `created_at` ascending order."""
        params.setdefault("limit", 100)
        response = self.client.list_client_notifications(
            self.director, methodology_change_id=methodology_change_id, **params
        )
        return validate_success(response, 200)

    def acknowledge_all(self, methodology_change_id: str) -> List[Dict[str, Any]]:
        """Have every notified client acknowledge its own notification."""
        acknowledged = []
        for row in self.notifications_of_change(methodology_change_id):
            if row["state"] != "SENT":
                continue
            acknowledged.append(
                validate_success(
                    self.client.acknowledge_notification(
                        self.client_headers(row["client_id"]), row["id"]
                    ),
                    200,
                )
            )
        return acknowledged

    def activate_change(self, methodology_change_id: str, **overrides) -> Dict[str, Any]:
        """Activate under a director distinct from the one who drafted the change."""
        headers = overrides.pop("headers", self.activator)
        return validate_success(
            self.client.activate_methodology_change(headers, methodology_change_id), 200
        )

    # ------------------------------------------------------------------
    # Accreditation audits (PRD 3.9)
    # ------------------------------------------------------------------

    def open_audit(self, market_id: str, scope_edit_rule_set_id: str, **overrides) -> Dict[str, Any]:
        """Open an audit; the market's posture is driven to FROZEN at once."""
        headers = overrides.pop("headers", self.auditor)
        return get_success_data(
            self.client.create_accreditation_audit(
                headers, **accreditation_audit_payload(market_id, scope_edit_rule_set_id, **overrides)
            )
        )

    def finalize_audit(self, accreditation_audit_id: str, **overrides) -> Dict[str, Any]:
        """Finalize under an auditor distinct from the one who opened the audit."""
        headers = overrides.pop("headers", self.finalizer)
        return validate_success(
            self.client.finalize_accreditation_audit(
                headers, accreditation_audit_id, **finalize_audit_payload(**overrides)
            ),
            200,
        )

    def read_audit(self, accreditation_audit_id: str) -> Dict[str, Any]:
        """Re-read an audit to inspect its outcome and disclosures."""
        return get_success_data(
            self.client.get_accreditation_audit(self.auditor, accreditation_audit_id)
        )


# ======================================================================
# pytest fixtures
# ======================================================================

@pytest.fixture
def panel() -> PanelHarness:
    """The setup orchestrator, wired to the module-level client instance."""
    return PanelHarness(api_client)


@pytest.fixture
def client() -> ApiClient:
    """The raw client, for tests that need to drive one endpoint directly."""
    return api_client


@pytest.fixture
def panel_ops() -> Dict[str, str]:
    """Headers for the default `PanelOperationsManager` operator."""
    return make_panel_ops_headers()


@pytest.fixture
def field_tech() -> Dict[str, str]:
    """Headers for the default `FieldTechnician` operator."""
    return make_field_tech_headers()


@pytest.fixture
def statistician() -> Dict[str, str]:
    """Headers for the `MethodologyStatistician` who opens runs."""
    return make_statistician_headers(STATISTICIAN_USER_ID)


@pytest.fixture
def second_statistician() -> Dict[str, str]:
    """Headers for a distinct `MethodologyStatistician`, able to publish a run."""
    return make_statistician_headers(STATISTICIAN_PUBLISHER_USER_ID)


@pytest.fixture
def client_service() -> Dict[str, str]:
    """Headers for the default `ClientServiceRep` operator."""
    return make_client_service_headers()


@pytest.fixture
def auditor() -> Dict[str, str]:
    """Headers for the `AccreditationAuditor` who opens audits."""
    return make_auditor_headers(AUDITOR_USER_ID)


@pytest.fixture
def second_auditor() -> Dict[str, str]:
    """Headers for a distinct `AccreditationAuditor`, able to finalize."""
    return make_auditor_headers(AUDITOR_FINALIZER_USER_ID)


@pytest.fixture
def governance_director() -> Dict[str, str]:
    """Headers for the `GovernanceDirector` who drafts changes."""
    return make_director_headers(DIRECTOR_USER_ID)


@pytest.fixture
def second_director() -> Dict[str, str]:
    """Headers for a distinct `GovernanceDirector`, able to activate."""
    return make_director_headers(DIRECTOR_ACTIVATOR_USER_ID)


@pytest.fixture
def default_clock() -> str:
    """The instant the logical clock reads before it has ever been set."""
    return DEFAULT_CLOCK


@pytest.fixture
def market(panel: PanelHarness) -> Dict[str, Any]:
    """One freshly registered market, still holding no quota cells."""
    return panel.create_market()


@pytest.fixture
def market_with_cell(panel: PanelHarness) -> Dict[str, Any]:
    """A market and its single UNDER_TARGET cell with the boost armed."""
    market, cells = panel.market_with_cells()
    return {"market": market, "cell": cells[0], "cells": cells}


@pytest.fixture
def measurement_base(panel: PanelHarness) -> Dict[str, Any]:
    """A market, one cell, a PUBLISHED rule set and a PUBLISHED vintage."""
    return panel.measurement_base()


@pytest.fixture
def active_panel(panel: PanelHarness) -> Dict[str, Any]:
    """One in-tab household with a single 600-minute block, clock at T1."""
    return panel.panel_with_data(
        household_specs=[{"intervals": [(WINDOW_START, "2026-08-01T10:00:00Z", 600)]}]
    )


@pytest.fixture
def edited_run(panel: PanelHarness) -> Dict[str, Any]:
    """The canonical chain carried to an EDITED run."""
    return panel.edited_run()


@pytest.fixture
def weighted_run(panel: PanelHarness) -> Dict[str, Any]:
    """The canonical chain carried to a WEIGHTED run under FINAL."""
    return panel.weighted_run()


@pytest.fixture
def published_run(panel: PanelHarness) -> Dict[str, Any]:
    """The canonical chain carried to a terminal PUBLISHED run."""
    return panel.published_run()


@pytest.fixture
def subscribed_run(panel: PanelHarness) -> Dict[str, Any]:
    """A PUBLISHED run plus a STANDARD client contracted to its market."""
    return panel.subscribed_published_run()
