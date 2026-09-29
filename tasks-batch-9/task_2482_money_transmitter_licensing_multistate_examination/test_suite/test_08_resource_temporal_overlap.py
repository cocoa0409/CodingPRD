"""Temporal overlap over two resources with two different interval semantics.

An examination window is the half-open interval [fieldwork_start, fieldwork_end)
widened at both ends by a thirty-day cooling-off buffer whose comparison is
strict, so a window starting exactly thirty days after another's end is
admissible. A delegate authorization period is the closed interval
[effective_date, expiry_date] scoped per delegate *and* per jurisdiction, so
touching endpoints collide, a one-day gap is required, and the identical
calendar period under another state's licence is admitted.

Every colliding case below is paired with the adjacent admissible case so that
each boundary is pinned from both sides.
"""

from typing import Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DELEGATE_PERIOD_OVERLAP,
    ERR_EXAM_WINDOW_CONFLICT,
)
from test_helpers.test_users import MANAGER_HEADERS, make_state_regulator_headers


def _licensee_licensed_in_two_states(
    api: MoneyTransmitterApiClient,
) -> Tuple[fx.Scenario, dict]:
    """One licensee holding an ACTIVE licence in California and in Texas.

    The California bond is base_bond 5_000_000 and the Texas bond is base_bond
    30_000_000; both dominate the tier-one bond of 2_500_000 at the seeded
    projected volume, and both jurisdictions have participates_in_multistate true.
    """
    scenario = fx.setup_active_license(api, C.CA_CONFIG)
    texas = fx.add_license_in_jurisdiction(api, scenario.licensee_id, C.TX_CONFIG)
    assert texas["license"]["license_status"] == "ACTIVE"
    scenario.extra["tx"] = texas
    return scenario, texas


# ---------------------------------------------------------------------------
# MultistateExam fieldwork windows and the thirty-day cooling-off buffer
# ---------------------------------------------------------------------------


def test_exam_window_starting_inside_the_thirty_day_buffer_is_rejected(
    api: MoneyTransmitterApiClient,
) -> None:
    """A second examination beginning before the first one's end plus thirty days collides.

    PRD 3.8: "Examinations of one licensee are also kept apart by a thirty-day cooling-off buffer: a new window is rejected with `ERR_EXAM_WINDOW_CONFLICT` (HTTP 409) whenever some other examination of the same licensee has a window such that the new `fieldwork_start` falls before that examination's `fieldwork_end` extended by thirty days **and** that examination's `fieldwork_start` falls before the new `fieldwork_end` extended by thirty days."
    PRD 2.4: "Day arithmetic on the clock adds exact multiples of twenty-four hours, and all instants are millisecond-exact ISO 8601 UTC."
    PRD 3.8: "On success the exam starts in `SCHEDULED` and `participating_state_count` is set to the distinct count of participating jurisdictions including the lead."

    Design: Difficulty/resource_temporal_overlap/exam_fieldwork_windows_collide_inside_thirty_day_cooling_off
    """
    scenario, texas = _licensee_licensed_in_two_states(api)
    ca_id, tx_id = scenario.jurisdiction_id, texas["jurisdiction"]["id"]

    first = fx.schedule_exam(
        api,
        scenario.licensee_id,
        ca_id,
        "2026-09-01T00:00:00Z",
        "2026-09-15T00:00:00Z",
        participating_jurisdiction_ids=[ca_id, tx_id],
    )
    assert first["status"] == "SCHEDULED"
    # Distinct participants including the lead: CA and TX.
    assert first["participating_state_count"] == 2

    # 2026-09-15 extended by thirty days is 2026-10-15, and 2026-10-10 falls
    # before it; the first exam's 2026-09-01 start also falls before the new
    # 2026-10-20 end extended by thirty days (2026-11-19), so both legs hold.
    response = api.create_exam(
        F.exam_payload(
            scenario.licensee_id,
            tx_id,
            "2026-10-10T00:00:00Z",
            "2026-10-20T00:00:00Z",
            participating_jurisdiction_ids=[tx_id, ca_id],
        ),
        make_state_regulator_headers(tx_id),
    )
    validate_error(response, ERR_EXAM_WINDOW_CONFLICT)

    unchanged = get_success_data(api.get_exam(first["id"], MANAGER_HEADERS))
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["fieldwork_start"][:10] == "2026-09-01"
    assert unchanged["fieldwork_end"][:10] == "2026-09-15"
    rows, meta = validate_paginated(
        api.list_exams(MANAGER_HEADERS, params={"licensee_id": scenario.licensee_id})
    )
    # The rejected schedule left nothing behind.
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_exam_window_starting_exactly_thirty_days_after_the_end_is_admissible(
    api: MoneyTransmitterApiClient,
) -> None:
    """The adjacent clear case: a start exactly at end-plus-thirty clears the strict buffer test.

    PRD 3.8: "Examinations of one licensee are also kept apart by a thirty-day cooling-off buffer: a new window is rejected with `ERR_EXAM_WINDOW_CONFLICT` (HTTP 409) whenever some other examination of the same licensee has a window such that the new `fieldwork_start` falls before that examination's `fieldwork_end` extended by thirty days **and** that examination's `fieldwork_start` falls before the new `fieldwork_end` extended by thirty days."
    PRD 3.8: "On success the exam starts in `SCHEDULED` and `participating_state_count` is set to the distinct count of participating jurisdictions including the lead."
    PRD 3.8: "The remaining statuses are `FIELDWORK`, `REPORT_DRAFT`, `REPORT_ISSUED` and the terminal `CLOSED`; `open_request_count` and `findings_count` both start at zero."
    PRD 3.8: "Every listed participant must be eligible — its `participates_in_multistate` must be true and the examined licensee must hold a `StateLicense` there whose `license_status` is `ACTIVE`; a participant failing either test is rejected with `ERR_JURISDICTION_NOT_MULTISTATE` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/exam_fieldwork_windows_collide_inside_thirty_day_cooling_off
    """
    scenario, texas = _licensee_licensed_in_two_states(api)
    ca_id, tx_id = scenario.jurisdiction_id, texas["jurisdiction"]["id"]

    first = fx.schedule_exam(
        api,
        scenario.licensee_id,
        ca_id,
        "2026-09-01T00:00:00Z",
        "2026-09-15T00:00:00Z",
        participating_jurisdiction_ids=[ca_id, tx_id],
    )

    colliding = api.create_exam(
        F.exam_payload(
            scenario.licensee_id,
            tx_id,
            "2026-10-10T00:00:00Z",
            "2026-10-20T00:00:00Z",
            participating_jurisdiction_ids=[tx_id, ca_id],
        ),
        make_state_regulator_headers(tx_id),
    )
    validate_error(colliding, ERR_EXAM_WINDOW_CONFLICT)

    # 2026-09-15 plus thirty exact days is 2026-10-15, and 2026-10-15 does not
    # fall *before* 2026-10-15, so the first leg of the buffer test fails and the
    # window is admissible.
    second = validate_success(
        api.create_exam(
            F.exam_payload(
                scenario.licensee_id,
                tx_id,
                "2026-10-15T00:00:00Z",
                "2026-10-25T00:00:00Z",
                participating_jurisdiction_ids=[tx_id, ca_id],
            ),
            make_state_regulator_headers(tx_id),
        ),
        201,
    )
    assert second["status"] == "SCHEDULED"
    # Distinct participants including the lead: TX and CA.
    assert second["participating_state_count"] == 2
    assert second["open_request_count"] == 0
    assert second["findings_count"] == 0
    assert second["lead_jurisdiction_id"] == tx_id

    still_scheduled = get_success_data(api.get_exam(first["id"], MANAGER_HEADERS))
    assert still_scheduled["status"] == "SCHEDULED"

    rows, meta = validate_paginated(
        api.list_exams(MANAGER_HEADERS, params={"licensee_id": scenario.licensee_id})
    )
    # Exactly the first exam and the admitted second one.
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {first["id"], second["id"]}


def test_exam_window_ending_before_the_buffer_pins_the_second_leg_from_both_sides(
    api: MoneyTransmitterApiClient,
) -> None:
    """An earlier window collides only while the existing start precedes the new end plus thirty days.

    PRD 3.8: "Examinations of one licensee are also kept apart by a thirty-day cooling-off buffer: a new window is rejected with `ERR_EXAM_WINDOW_CONFLICT` (HTTP 409) whenever some other examination of the same licensee has a window such that the new `fieldwork_start` falls before that examination's `fieldwork_end` extended by thirty days **and** that examination's `fieldwork_start` falls before the new `fieldwork_end` extended by thirty days."
    PRD 3.8: "A `StateRegulator` schedules a `MultistateExam` for a `licensee_id`, naming itself as `lead_jurisdiction_id` and listing the `participating_jurisdiction_ids` that are joining, together with a field window: `fieldwork_start` is inclusive and `fieldwork_end`, which must be strictly later, is exclusive."
    PRD 2.4: "Day arithmetic on the clock adds exact multiples of twenty-four hours, and all instants are millisecond-exact ISO 8601 UTC."

    Design: Difficulty/resource_temporal_overlap/exam_fieldwork_windows_collide_inside_thirty_day_cooling_off
    """
    scenario, texas = _licensee_licensed_in_two_states(api)
    ca_id, tx_id = scenario.jurisdiction_id, texas["jurisdiction"]["id"]

    fx.schedule_exam(
        api,
        scenario.licensee_id,
        ca_id,
        "2026-09-01T00:00:00Z",
        "2026-09-15T00:00:00Z",
        participating_jurisdiction_ids=[ca_id, tx_id],
    )

    # 2026-08-03 plus thirty exact days is 2026-09-02, and the existing start of
    # 2026-09-01 falls before it; the new 2026-07-01 start also falls before
    # 2026-10-15, so both legs hold and the window collides.
    colliding = api.create_exam(
        F.exam_payload(
            scenario.licensee_id,
            tx_id,
            "2026-07-01T00:00:00Z",
            "2026-08-03T00:00:00Z",
            participating_jurisdiction_ids=[tx_id, ca_id],
        ),
        make_state_regulator_headers(tx_id),
    )
    validate_error(colliding, ERR_EXAM_WINDOW_CONFLICT)

    # One day earlier: 2026-08-02 plus thirty exact days is 2026-09-01, and the
    # existing start of 2026-09-01 does not fall before it, so the second leg
    # fails and the window is admissible.
    admitted = validate_success(
        api.create_exam(
            F.exam_payload(
                scenario.licensee_id,
                tx_id,
                "2026-07-01T00:00:00Z",
                "2026-08-02T00:00:00Z",
                participating_jurisdiction_ids=[tx_id, ca_id],
            ),
            make_state_regulator_headers(tx_id),
        ),
        201,
    )
    assert admitted["status"] == "SCHEDULED"
    assert admitted["participating_state_count"] == 2

    _rows, meta = validate_paginated(
        api.list_exams(MANAGER_HEADERS, params={"licensee_id": scenario.licensee_id})
    )
    # The first exam plus the admitted earlier window; the rejected one is absent.
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# DelegateAuthorization periods: closed at both ends, scoped per jurisdiction
# ---------------------------------------------------------------------------


def _delegate_with_a_september_ca_period(
    api: MoneyTransmitterApiClient, scenario: fx.Scenario
) -> Tuple[dict, dict]:
    """One delegate holding a PENDING_OVERSIGHT CA period of 2026-09-01..2026-09-30."""
    delegate = fx.create_delegate(api, scenario.licensee_id)
    authorization = fx.create_authorization(
        api,
        delegate["id"],
        scenario.license_id,
        "2026-09-01T00:00:00Z",
        "2026-09-30T00:00:00Z",
    )
    assert authorization["status"] == "PENDING_OVERSIGHT"
    return delegate, authorization


def test_authorization_period_touching_the_existing_expiry_collides(
    api: MoneyTransmitterApiClient,
) -> None:
    """A new period whose effective date equals the existing expiry date is rejected.

    PRD 3.6: "The interval is closed at both ends."
    PRD 3.6: "And within a single jurisdiction, one delegate may not hold two overlapping authorizations: a new authorization is rejected with `ERR_DELEGATE_PERIOD_OVERLAP` (HTTP 409) whenever some other non-`TERMINATED` authorization of the same delegate under a licence of the **same** jurisdiction has an interval that overlaps or merely touches the new one — formally, whenever the new `effective_date` is on or before the existing `expiry_date` and the existing `effective_date` is on or before the new `expiry_date`."
    PRD 3.6: "Touching endpoints collide; at least a one-day gap is required."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."

    Design: Difficulty/resource_temporal_overlap/delegate_authorization_periods_touch_and_collide_per_jurisdiction
    """
    scenario, _texas = _licensee_licensed_in_two_states(api)
    delegate, _existing = _delegate_with_a_september_ca_period(api, scenario)

    # New effective 2026-09-30 is on or before the existing expiry 2026-09-30, and
    # the existing effective 2026-09-01 is on or before the new expiry 2026-10-31.
    response = api.create_delegate_authorization(
        F.delegate_authorization_payload(
            delegate["id"],
            scenario.license_id,
            "2026-09-30T00:00:00Z",
            "2026-10-31T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(response, ERR_DELEGATE_PERIOD_OVERLAP)

    rows, meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"delegate_id": delegate["id"]}
        )
    )
    # Only the pre-existing September period survives the rejected create.
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "PENDING_OVERSIGHT"

    unmoved = fx.get_license(api, scenario.license_id)
    assert unmoved["active_delegate_count"] == 0


def test_authorization_period_one_day_after_the_existing_expiry_is_admissible(
    api: MoneyTransmitterApiClient,
) -> None:
    """The adjacent clear case: the one-day gap the closed interval demands is accepted.

    PRD 3.6: "And within a single jurisdiction, one delegate may not hold two overlapping authorizations: a new authorization is rejected with `ERR_DELEGATE_PERIOD_OVERLAP` (HTTP 409) whenever some other non-`TERMINATED` authorization of the same delegate under a licence of the **same** jurisdiction has an interval that overlaps or merely touches the new one — formally, whenever the new `effective_date` is on or before the existing `expiry_date` and the existing `effective_date` is on or before the new `expiry_date`."
    PRD 3.6: "Touching endpoints collide; at least a one-day gap is required."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."
    PRD 3.6: "The remaining statuses are `ACTIVE`, `SUSPENDED_BY_POSTURE`, `SUSPENDED` and the terminal `TERMINATED`; `activated_at` and `oversight_score_at_activation` both start null."

    Design: Difficulty/resource_temporal_overlap/delegate_authorization_periods_touch_and_collide_per_jurisdiction
    """
    scenario, _texas = _licensee_licensed_in_two_states(api)
    delegate, _existing = _delegate_with_a_september_ca_period(api, scenario)

    touching = api.create_delegate_authorization(
        F.delegate_authorization_payload(
            delegate["id"],
            scenario.license_id,
            "2026-09-30T00:00:00Z",
            "2026-10-31T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(touching, ERR_DELEGATE_PERIOD_OVERLAP)

    # New effective 2026-10-01 is not on or before the existing expiry 2026-09-30,
    # so the first leg of the closed-interval test fails.
    admitted = validate_success(
        api.create_delegate_authorization(
            F.delegate_authorization_payload(
                delegate["id"],
                scenario.license_id,
                "2026-10-01T00:00:00Z",
                "2026-10-31T00:00:00Z",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert admitted["status"] == "PENDING_OVERSIGHT"
    assert admitted["activated_at"] is None
    assert admitted["oversight_score_at_activation"] is None

    _rows, meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"delegate_id": delegate["id"]}
        )
    )
    # The September period plus the admitted October period.
    assert meta["total_count"] == 2

    unmoved = fx.get_license(api, scenario.license_id)
    assert unmoved["active_delegate_count"] == 0
    unmoved_delegate = get_success_data(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert unmoved_delegate["authorized_state_count"] == 0
    assert unmoved_delegate["status"] == "ONBOARDING"


def test_authorization_period_touching_the_existing_effective_date_collides(
    api: MoneyTransmitterApiClient,
) -> None:
    """The other endpoint pinned from both sides: a new expiry equal to the existing effective date collides.

    PRD 3.6: "And within a single jurisdiction, one delegate may not hold two overlapping authorizations: a new authorization is rejected with `ERR_DELEGATE_PERIOD_OVERLAP` (HTTP 409) whenever some other non-`TERMINATED` authorization of the same delegate under a licence of the **same** jurisdiction has an interval that overlaps or merely touches the new one — formally, whenever the new `effective_date` is on or before the existing `expiry_date` and the existing `effective_date` is on or before the new `expiry_date`."
    PRD 3.6: "Touching endpoints collide; at least a one-day gap is required."
    PRD 3.6: "The interval is closed at both ends."

    Design: Difficulty/resource_temporal_overlap/delegate_authorization_periods_touch_and_collide_per_jurisdiction
    """
    scenario, _texas = _licensee_licensed_in_two_states(api)
    delegate, _existing = _delegate_with_a_september_ca_period(api, scenario)

    # Existing effective 2026-09-01 is on or before the new expiry 2026-09-01, and
    # the new effective 2026-08-01 is on or before the existing expiry 2026-09-30.
    colliding = api.create_delegate_authorization(
        F.delegate_authorization_payload(
            delegate["id"],
            scenario.license_id,
            "2026-08-01T00:00:00Z",
            "2026-09-01T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(colliding, ERR_DELEGATE_PERIOD_OVERLAP)

    # One day earlier: existing effective 2026-09-01 is not on or before the new
    # expiry 2026-08-31, so the second leg fails and the period is admissible.
    admitted = validate_success(
        api.create_delegate_authorization(
            F.delegate_authorization_payload(
                delegate["id"],
                scenario.license_id,
                "2026-08-01T00:00:00Z",
                "2026-08-31T00:00:00Z",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert admitted["status"] == "PENDING_OVERSIGHT"

    _rows, meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"delegate_id": delegate["id"]}
        )
    )
    # The September period plus the admitted August period.
    assert meta["total_count"] == 2


def test_identical_period_under_another_jurisdictions_licence_is_admissible(
    api: MoneyTransmitterApiClient,
) -> None:
    """Overlap is scoped per delegate AND per jurisdiction, so the same calendar period is legal in Texas.

    PRD 3.6: "And within a single jurisdiction, one delegate may not hold two overlapping authorizations: a new authorization is rejected with `ERR_DELEGATE_PERIOD_OVERLAP` (HTTP 409) whenever some other non-`TERMINATED` authorization of the same delegate under a licence of the **same** jurisdiction has an interval that overlaps or merely touches the new one — formally, whenever the new `effective_date` is on or before the existing `expiry_date` and the existing `effective_date` is on or before the new `expiry_date`."
    PRD 3.6: "The appointment is made concrete per state by a `DelegateAuthorization`, which pairs a `delegate_id` with a `state_license_id` and defines a period and a limit: `effective_date` is the first day of the authorization period, `expiry_date` is the last day and may not precede the effective date, and `monthly_volume_cap_cents` is the contractual monthly transmission cap, which must be strictly greater than zero."
    PRD 3.6: "A new authorization starts in `PENDING_OVERSIGHT` and moves no counter — only activation makes a delegate count against the bond."

    Design: Difficulty/resource_temporal_overlap/delegate_authorization_periods_touch_and_collide_per_jurisdiction
    """
    scenario, texas = _licensee_licensed_in_two_states(api)
    tx_license_id = texas["license"]["id"]
    delegate, _existing = _delegate_with_a_september_ca_period(api, scenario)

    # The same period again under the California licence collides.
    colliding = api.create_delegate_authorization(
        F.delegate_authorization_payload(
            delegate["id"],
            scenario.license_id,
            "2026-09-01T00:00:00Z",
            "2026-09-30T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(colliding, ERR_DELEGATE_PERIOD_OVERLAP)

    # The identical period under the Texas licence is a different jurisdiction and
    # is therefore outside the scope of the overlap test.
    admitted = validate_success(
        api.create_delegate_authorization(
            F.delegate_authorization_payload(
                delegate["id"],
                tx_license_id,
                "2026-09-01T00:00:00Z",
                "2026-09-30T00:00:00Z",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert admitted["status"] == "PENDING_OVERSIGHT"
    assert admitted["state_license_id"] == tx_license_id
    assert admitted["effective_date"][:10] == "2026-09-01"
    assert admitted["expiry_date"][:10] == "2026-09-30"

    _rows, meta = validate_paginated(
        api.list_delegate_authorizations(
            MANAGER_HEADERS, params={"delegate_id": delegate["id"]}
        )
    )
    # The California period plus the Texas period; the rejected duplicate is absent.
    assert meta["total_count"] == 2

    assert fx.get_license(api, scenario.license_id)["active_delegate_count"] == 0
    assert fx.get_license(api, tx_license_id)["active_delegate_count"] == 0


def test_a_terminated_period_no_longer_collides(
    api: MoneyTransmitterApiClient,
) -> None:
    """Only non-TERMINATED periods are in the overlap set, so terminating clears the touching period.

    PRD 3.6: "And within a single jurisdiction, one delegate may not hold two overlapping authorizations: a new authorization is rejected with `ERR_DELEGATE_PERIOD_OVERLAP` (HTTP 409) whenever some other non-`TERMINATED` authorization of the same delegate under a licence of the **same** jurisdiction has an interval that overlaps or merely touches the new one — formally, whenever the new `effective_date` is on or before the existing `expiry_date` and the existing `effective_date` is on or before the new `expiry_date`."
    PRD 3.6: "Termination is the compensating action and is admissible from every non-`TERMINATED` status."
    PRD 3.6: "The authorization moves to the terminal `TERMINATED` with an optional `reason`."
    PRD 3.6: "If it had only been `PENDING_OVERSIGHT`, no counter moves, because the row was never counted."

    Design: Difficulty/resource_temporal_overlap/delegate_authorization_periods_touch_and_collide_per_jurisdiction
    """
    scenario, _texas = _licensee_licensed_in_two_states(api)
    delegate, existing = _delegate_with_a_september_ca_period(api, scenario)

    colliding = api.create_delegate_authorization(
        F.delegate_authorization_payload(
            delegate["id"],
            scenario.license_id,
            "2026-09-30T00:00:00Z",
            "2026-10-31T00:00:00Z",
        ),
        MANAGER_HEADERS,
    )
    validate_error(colliding, ERR_DELEGATE_PERIOD_OVERLAP)

    terminated = fx.terminate_authorization(api, existing["id"])
    assert terminated["status"] == "TERMINATED"

    admitted = validate_success(
        api.create_delegate_authorization(
            F.delegate_authorization_payload(
                delegate["id"],
                scenario.license_id,
                "2026-09-30T00:00:00Z",
                "2026-10-31T00:00:00Z",
            ),
            MANAGER_HEADERS,
        ),
        201,
    )
    assert admitted["status"] == "PENDING_OVERSIGHT"

    unmoved = fx.get_license(api, scenario.license_id)
    # The terminated row had only ever been PENDING_OVERSIGHT, so no counter moved.
    assert unmoved["active_delegate_count"] == 0
