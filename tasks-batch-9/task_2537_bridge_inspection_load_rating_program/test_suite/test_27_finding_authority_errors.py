"""
What a critical finding must be anchored to, how far the authority over one
reaches, and where the licence gate on a scour evaluation actually sits.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import make_rating_engineer_headers

FIRST_WINDOW_START = "2026-09-02T08:00:00Z"
FIRST_WINDOW_END = "2026-09-02T16:00:00Z"
SECOND_WINDOW_START = "2026-09-10T08:00:00Z"
SECOND_WINDOW_END = "2026-09-10T16:00:00Z"

# An abutment undermined at the surface: three units poor, none severe, so it is a
# legitimate anchor for an `URGENT` finding and an illegitimate one for `IMMEDIATE`.
UNDERMINED_ABUTMENT = f.element_condition_payload(
    "ABUTMENT",
    "EA",
    4,
    0,
    1,
    3,
    0,
    photo_count=2,
    defect_notes="Undermined footing face, no section loss",
)


def _one_submitted_report_and_a_second_report_of_its_own(client, roster, bridge):
    """
    Cedar Creek with a `SUBMITTED` report A — a deck, a girder carrying 100 units of
    severe defect and an abutment carrying none — and a separate `DRAFT` report B
    eight days later holding a deck row of its own, so an element of the same
    structure can be offered as a foreign anchor.
    """
    report_a = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=FIRST_WINDOW_START,
        field_window_end=FIRST_WINDOW_END,
    )
    fx.add_element(client, report_a["id"], roster, f.BASELINE_DECK)
    girder = fx.add_element(client, report_a["id"], roster, f.BASELINE_GIRDER)
    abutment = fx.add_element(client, report_a["id"], roster, UNDERMINED_ABUTMENT)

    report_b = fx.open_inspection(
        client,
        bridge["id"],
        roster,
        field_window_start=SECOND_WINDOW_START,
        field_window_end=SECOND_WINDOW_END,
    )
    deck_of_b = fx.add_element(client, report_b["id"], roster, f.BASELINE_DECK)

    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    submitted = fx.submit_report(client, report_a["id"], roster)
    return {
        "report_a": submitted,
        "report_b": report_b,
        "girder": girder,
        "abutment": abutment,
        "deck_of_b": deck_of_b,
    }


def test_an_element_belonging_to_another_report_cannot_anchor_the_finding(
    client, roster, bridge
):
    """
    Every identifier in the payload exists and the named structure is right, but the
    element was recorded on report B while the finding cites report A, so the anchor
    fails on provenance before its substance is ever considered.

    PRD §3.5: "When an `element_condition_id` is supplied it must belong to the named
    source report, and that report must belong to the named structure; a mismatch is
    `ERR_ELEMENT_INSPECTION_MISMATCH`."
    PRD §2.8: "20. **Element-to-inspection anchoring** —
    `ERR_ELEMENT_INSPECTION_MISMATCH` (422). Applies to critical-finding creation."

    Design: Corner/errors/critical_finding_foreign_element_and_missing_cs4_anchor_rejected
    """
    setup = _one_submitted_report_and_a_second_report_of_its_own(client, roster, bridge)

    response = client.create_critical_finding(
        f.critical_finding_payload(
            bridge["id"],
            setup["report_a"]["id"],
            "IMMEDIATE",
            description="Girder web loss threatening collapse",
            element_condition_id=setup["deck_of_b"]["id"],
        ),
        roster.inspector_headers,
    )

    validate_error(response, e.ERR_ELEMENT_INSPECTION_MISMATCH, 422)
    assert setup["deck_of_b"]["inspection_id"] == setup["report_b"]["id"]
    assert setup["deck_of_b"]["cs4_qty"] == 50, (
        "the foreign anchor does carry severe quantity, so the substance rule "
        "cannot be what refused it"
    )
    assert (
        response.json()["data"]["error_id"] != e.ERR_NO_CS4_DEFICIENCY
    ), "provenance is checked before substance"


def test_an_immediate_finding_needs_a_severe_quantity_but_an_urgent_one_does_not(
    client, roster, bridge
):
    """
    The abutment belongs to the cited report, so provenance passes and substance
    decides: three units of poor condition do not license an immediate finding, while
    the very same anchor carries an urgent one.

    PRD §3.5: "Severity then decides how strict the anchoring is: an `IMMEDIATE`
    finding **must** name an `element_condition_id` whose `cs4_qty` is greater than
    zero, because immediate danger has to be anchored to a quantified severe defect,
    and a violation is `ERR_NO_CS4_DEFICIENCY`; an `URGENT` finding may omit
    `element_condition_id` entirely."
    PRD §2.8: "21. **Immediate severity anchoring** — `ERR_NO_CS4_DEFICIENCY` (422).
    Applies to critical-finding creation."

    Design: Corner/errors/critical_finding_foreign_element_and_missing_cs4_anchor_rejected
    """
    setup = _one_submitted_report_and_a_second_report_of_its_own(client, roster, bridge)

    refused = client.create_critical_finding(
        f.critical_finding_payload(
            bridge["id"],
            setup["report_a"]["id"],
            "IMMEDIATE",
            description="Abutment undermining",
            element_condition_id=setup["abutment"]["id"],
        ),
        roster.inspector_headers,
    )

    validate_error(refused, e.ERR_NO_CS4_DEFICIENCY, 422)
    assert setup["abutment"]["cs3_qty"] == 3
    assert setup["abutment"]["cs4_qty"] == 0

    urgent = get_success_data(
        client.create_critical_finding(
            f.critical_finding_payload(
                bridge["id"],
                setup["report_a"]["id"],
                "URGENT",
                description="Abutment undermining, monitor",
                element_condition_id=setup["abutment"]["id"],
            ),
            roster.inspector_headers,
        ),
        201,
    )
    assert urgent["severity"] == "URGENT"
    assert urgent["element_condition_id"] == setup["abutment"]["id"]


def test_the_two_accepted_findings_are_counted_and_the_two_refusals_are_not(
    client, roster, bridge
):
    """
    Both refusals run first and then both legitimate findings are raised: the
    structure's open counter ends at two, which is the count of findings that exist
    rather than of attempts that were made.

    PRD §3.5: "A new finding is created with `finding_status` `OPEN`,
    `notification_status` `PENDING` and `restriction_action` `NONE`."
    PRD §3.5: "Creating the finding also increments the structure's
    `open_critical_finding_count`, which counts findings on that structure whose
    `finding_status` is `OPEN` or `MITIGATED`, and increments the structure's `version`
    by one."

    Design: Corner/errors/critical_finding_foreign_element_and_missing_cs4_anchor_rejected
    """
    setup = _one_submitted_report_and_a_second_report_of_its_own(client, roster, bridge)
    before = fx.read_bridge(client, bridge["id"])
    validate_error(
        client.create_critical_finding(
            f.critical_finding_payload(
                bridge["id"],
                setup["report_a"]["id"],
                "IMMEDIATE",
                element_condition_id=setup["deck_of_b"]["id"],
            ),
            roster.inspector_headers,
        ),
        e.ERR_ELEMENT_INSPECTION_MISMATCH,
        422,
    )
    validate_error(
        client.create_critical_finding(
            f.critical_finding_payload(
                bridge["id"],
                setup["report_a"]["id"],
                "IMMEDIATE",
                element_condition_id=setup["abutment"]["id"],
            ),
            roster.inspector_headers,
        ),
        e.ERR_NO_CS4_DEFICIENCY,
        422,
    )
    assert (
        fx.read_bridge(client, bridge["id"])["open_critical_finding_count"]
        == before["open_critical_finding_count"]
    )

    fx.raise_finding(
        client,
        roster,
        bridge["id"],
        setup["report_a"]["id"],
        "URGENT",
        element_condition_id=setup["abutment"]["id"],
    )
    immediate = fx.raise_finding(
        client,
        roster,
        bridge["id"],
        setup["report_a"]["id"],
        "IMMEDIATE",
        element_condition_id=setup["girder"]["id"],
    )

    assert immediate["finding_status"] == "OPEN"
    assert immediate["notification_status"] == "PENDING"
    assert immediate["restriction_action"] == "NONE"
    assert fx.read_bridge(client, bridge["id"])["open_critical_finding_count"] == 2


# ─── How far the authority over an urgent finding reaches ────────────────────
def _one_urgent_finding_on_an_open_structure(client, roster, bridge):
    """
    An `URGENT` finding raised from a `SUBMITTED` report at the field-day clock, on a
    structure that is still fully open, with the district engineer — who is not the
    report's team leader — free to exercise authority over it.
    """
    drafted = fx.draft_report_with_baseline(
        client,
        bridge["id"],
        roster,
        field_window_start=FIRST_WINDOW_START,
        field_window_end=FIRST_WINDOW_END,
    )
    fx.set_clock(client, c.FIELD_DAY_CLOCK)
    submitted = fx.submit_report(client, drafted["inspection"]["id"], roster)
    finding = fx.raise_finding(
        client,
        roster,
        bridge["id"],
        submitted["id"],
        "URGENT",
        description="Abutment undermining after high water",
    )
    return {"inspection": submitted, "finding": finding}


def test_closure_is_refused_on_an_urgent_finding(client, roster, bridge):
    """
    The restriction dimension is at its starting value, so the state gate is
    satisfied and the only objection left is the severity the closure would need.

    PRD §3.5: "Escalating to `CLOSE` is permitted from `restriction_action` `NONE` or
    `RESTRICT`, and it additionally requires the finding's `severity` to be
    `IMMEDIATE`; requesting closure on an `URGENT` finding is
    `ERR_SEVERITY_INSUFFICIENT_FOR_CLOSURE`."
    PRD §2.8: "22. **Closure severity** — `ERR_SEVERITY_INSUFFICIENT_FOR_CLOSURE`
    (422). Applies to restriction imposition."

    Design: Corner/errors/close_on_urgent_finding_and_out_of_order_notification_rejected
    """
    setup = _one_urgent_finding_on_an_open_structure(client, roster, bridge)

    response = client.impose_restriction(
        setup["finding"]["id"],
        f.restriction_payload("CLOSE", roster.district_id),
        roster.district_headers,
    )

    validate_error(response, e.ERR_SEVERITY_INSUFFICIENT_FOR_CLOSURE, 422)
    unchanged = fx.read_finding(client, setup["finding"]["id"])
    assert unchanged["severity"] == "URGENT"
    assert unchanged["restriction_action"] == "NONE"
    assert unchanged["restriction_imposed_at"] is None
    assert unchanged["restriction_authorized_by_id"] is None
    assert fx.read_bridge(client, bridge["id"])["service_posture"] == "OPEN"


def test_restriction_short_of_closure_is_allowed_on_the_same_finding(
    client, roster, bridge
):
    """
    Only closure is severity-gated: the identical act of authority at the lesser
    action succeeds on the same urgent finding and moves the structure down one rung
    of the posture ladder.

    PRD §3.5: "Escalating to `RESTRICT` is permitted only from `restriction_action`
    `NONE`. It stores `RESTRICT`, records `restriction_authorized_by_id` and stamps
    `restriction_imposed_at` from the logical clock. The structure's posture is then
    recomputed: a structure that was `OPEN` moves `OPEN → RESTRICTED`".

    Design: Corner/errors/close_on_urgent_finding_and_out_of_order_notification_rejected
    """
    setup = _one_urgent_finding_on_an_open_structure(client, roster, bridge)
    validate_error(
        client.impose_restriction(
            setup["finding"]["id"],
            f.restriction_payload("CLOSE", roster.district_id),
            roster.district_headers,
        ),
        e.ERR_SEVERITY_INSUFFICIENT_FOR_CLOSURE,
        422,
    )

    restricted = fx.impose(client, setup["finding"]["id"], roster, "RESTRICT")

    assert restricted["restriction_action"] == "RESTRICT"
    assert restricted["restriction_authorized_by_id"] == roster.district_id
    a.assert_instant_equals(
        restricted["restriction_imposed_at"], c.FIELD_DAY_CLOCK, "restriction_imposed_at"
    )
    assert fx.read_bridge(client, bridge["id"])["service_posture"] == "RESTRICTED"


def test_the_federal_tier_cannot_be_notified_before_the_owner(client, roster, bridge):
    """
    The chain has a first link and it is not the federal one: an out-of-order notice
    is refused and writes no audit row, leaving the finding still waiting to reach
    anybody.

    PRD §3.5: "The chain must be walked in tier order and neither tier may be walked
    twice: the `BRIDGE_OWNER` tier advances the finding `PENDING → OWNER_NOTIFIED`, and
    only from `OWNER_NOTIFIED` may the `FHWA` tier advance it to `FHWA_REPORTED`. An
    `FHWA` notice attempted before the owner has been notified, or a repeat of either
    tier, is rejected with `ERR_NOTIFICATION_SEQUENCE`."
    PRD §2.8: "23. **Notification chain order** — `ERR_NOTIFICATION_SEQUENCE` (409).
    Applies to finding notification."

    Design: Corner/errors/close_on_urgent_finding_and_out_of_order_notification_rejected
    """
    setup = _one_urgent_finding_on_an_open_structure(client, roster, bridge)

    response = client.notify_finding(
        setup["finding"]["id"],
        f.notify_payload("FHWA", recipient_label="FHWA Division Bridge Engineer"),
        roster.district_headers,
    )

    validate_error(response, e.ERR_NOTIFICATION_SEQUENCE, 409)
    assert fx.logs_for_finding(client, setup["finding"]["id"]) == []
    assert (
        fx.read_finding(client, setup["finding"]["id"])["notification_status"]
        == "PENDING"
    )


def test_the_owner_notice_lands_on_time_and_cannot_be_repeated(client, roster, bridge):
    """
    The owner link is walked inside the twenty-four hours it was given, so the log
    entry is not late, and walking the very same link again is refused with the same
    ordering code — a tier is single-use.

    PRD §3.5: "Its `notification_due_at` is set to its own `created_at` plus 24 hours —
    the deadline for reaching the bridge owner."
    PRD §3.5: "A log entry's `late` is true when its `tier` is `BRIDGE_OWNER` and its
    `sent_at` falls strictly after the finding's `notification_due_at`; an owner notice
    sent at exactly the deadline instant is on time, and one sent a single second later
    is late."

    Design: Corner/errors/close_on_urgent_finding_and_out_of_order_notification_rejected
    """
    setup = _one_urgent_finding_on_an_open_structure(client, roster, bridge)
    validate_error(
        client.notify_finding(
            setup["finding"]["id"],
            f.notify_payload("FHWA", recipient_label="FHWA Division Bridge Engineer"),
            roster.district_headers,
        ),
        e.ERR_NOTIFICATION_SEQUENCE,
        409,
    )

    logged = fx.notify_owner(
        client,
        setup["finding"]["id"],
        roster,
        channel="PHONE",
        recipient_label="County Highway Superintendent",
    )

    a.assert_notification_log_shape(logged)
    assert logged["critical_finding_id"] == setup["finding"]["id"]
    assert logged["tier"] == "BRIDGE_OWNER"
    assert logged["channel"] == "PHONE"
    assert logged["late"] is False
    a.assert_instant_equals(logged["sent_at"], c.FIELD_DAY_CLOCK, "sent_at")
    assert (
        fx.read_finding(client, setup["finding"]["id"])["notification_status"]
        == "OWNER_NOTIFIED"
    )

    repeat = client.notify_finding(
        setup["finding"]["id"],
        f.notify_payload(
            "BRIDGE_OWNER",
            channel="EMAIL",
            recipient_label="County Highway Superintendent (follow-up)",
        ),
        roster.district_headers,
    )

    validate_error(repeat, e.ERR_NOTIFICATION_SEQUENCE, 409)
    assert len(fx.logs_for_finding(client, setup["finding"]["id"])) == 1


# ─── Where the licence gate on a scour evaluation sits ───────────────────────
LOW_RISK_CODE = 5


def _three_rating_engineers_each_with_a_draft_evaluation(client, roster, bridge):
    """
    Three rating engineers with currently valid refreshers record one draft evaluation
    each on the water-crossing structure: Ulla is not licensed at all, Paul carries the
    licence flag but no licence number, and the roster's own engineer carries both.
    """
    ulla = fx.create_person(
        client,
        f.personnel_payload(
            "Ulla Unlicensed",
            fx.CURRENT_REFRESHER,
            load_rating_engineer_licensed=False,
        ),
    )
    paul = fx.create_person(
        client,
        f.personnel_payload(
            "Paul Pending",
            fx.CURRENT_REFRESHER,
            load_rating_engineer_licensed=True,
        ),
    )
    drafts = {}
    for person in (ulla, paul):
        drafts[person["full_name"]] = get_success_data(
            client.create_scour_evaluation(
                bridge["id"],
                f.scour_evaluation_payload(
                    person["id"],
                    LOW_RISK_CODE,
                    foundation_type="PILE",
                    observed_scour_depth_m=0.4,
                ),
                make_rating_engineer_headers(person["id"]),
            ),
            201,
        )
    drafts["Rita Rating"] = fx.create_scour_evaluation(
        client,
        bridge["id"],
        roster,
        LOW_RISK_CODE,
        foundation_type="PILE",
        observed_scour_depth_m=0.4,
    )
    return {"ulla": ulla, "paul": paul, "drafts": drafts}


def test_every_draft_evaluation_bands_the_code_without_touching_the_structure(
    client, roster, bridge
):
    """
    All three engineers may record an opinion regardless of licence, and each opinion
    bands the same code identically while the structure stays unevaluated — recording
    is not where the licence matters.

    PRD §3.6: "a code of 3 or below is `SCOUR_CRITICAL`, a code from 4 through 6 is
    `LOW_RISK`, and a code of 7 or above is `STABILIZED`."
    PRD §3.6: "A new evaluation is created with `status` `DRAFT` and a null
    `finalized_at`; while it remains a draft it is a working opinion and writes nothing
    through to the structure. A structure that has never had a finalised evaluation
    keeps a `scour_status` of `NOT_EVALUATED`, which is not a value
    `derived_scour_status` can ever take."

    Design: Corner/errors/scour_finalize_by_unlicensed_engineer_rejected
    """
    setup = _three_rating_engineers_each_with_a_draft_evaluation(client, roster, bridge)

    for label, draft in setup["drafts"].items():
        assert draft["status"] == "DRAFT", label
        assert draft["finalized_at"] is None, label
        assert draft["derived_scour_status"] == "LOW_RISK", label
        assert draft["bridge_id"] == bridge["id"], label
        assert draft["foundation_type"] == "PILE", label

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["scour_status"] == "NOT_EVALUATED"
    assert structure["version"] == 1


def test_an_unlicensed_engineer_cannot_finalise_her_own_evaluation(
    client, roster, bridge
):
    """
    The acting engineer holds the finalising role and owns the record she is
    finalising, so nothing but the missing licence flag can be the objection.

    PRD §3.6: "Only a `RatingEngineer` may finalise, and the engineer named in the
    evaluation's `evaluated_by_id` must hold `load_rating_engineer_licensed` with a
    non-null `pe_license_number` and a current refresher; otherwise the request fails
    with `ERR_RATING_ENGINEER_NOT_LICENSED`, the same gate that guards rating seals."
    PRD §2.8: "14. **Rating engineer licensing** — `ERR_RATING_ENGINEER_NOT_LICENSED`
    (422). Applies to load-rating sealing and scour-evaluation finalisation."

    Design: Corner/errors/scour_finalize_by_unlicensed_engineer_rejected
    """
    setup = _three_rating_engineers_each_with_a_draft_evaluation(client, roster, bridge)
    draft = setup["drafts"]["Ulla Unlicensed"]

    response = client.finalize_scour_evaluation(
        draft["id"], make_rating_engineer_headers(setup["ulla"]["id"])
    )

    validate_error(response, e.ERR_RATING_ENGINEER_NOT_LICENSED, 422)
    assert setup["ulla"]["load_rating_engineer_licensed"] is False
    assert setup["ulla"]["qualification_status"] == "CURRENT"
    still_draft = fx.read_scour(client, draft["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["finalized_at"] is None


def test_the_licence_flag_alone_is_not_enough_without_a_licence_number(
    client, roster, bridge
):
    """
    Paul claims the licence but records no number for it, and the gate reads both
    halves: the same refusal answers him, and the structure is still unevaluated after
    two rejected finalisations.

    PRD §2.10: "An engineer attempting to seal a rating or finalise a scour evaluation
    without `load_rating_engineer_licensed`, without a `pe_license_number`, or with an
    expired refresher is rejected with `ERR_RATING_ENGINEER_NOT_LICENSED` (HTTP 422)."
    PRD §2.10: "A licensed engineer must additionally carry a non-null
    `pe_license_number`; the field is null for anyone not licensed."

    Design: Corner/errors/scour_finalize_by_unlicensed_engineer_rejected
    """
    setup = _three_rating_engineers_each_with_a_draft_evaluation(client, roster, bridge)
    validate_error(
        client.finalize_scour_evaluation(
            setup["drafts"]["Ulla Unlicensed"]["id"],
            make_rating_engineer_headers(setup["ulla"]["id"]),
        ),
        e.ERR_RATING_ENGINEER_NOT_LICENSED,
        422,
    )

    response = client.finalize_scour_evaluation(
        setup["drafts"]["Paul Pending"]["id"],
        make_rating_engineer_headers(setup["paul"]["id"]),
    )

    validate_error(response, e.ERR_RATING_ENGINEER_NOT_LICENSED, 422)
    assert setup["paul"]["load_rating_engineer_licensed"] is True
    assert setup["paul"]["pe_license_number"] is None
    assert fx.read_scour(client, setup["drafts"]["Paul Pending"]["id"])["status"] == (
        "DRAFT"
    )
    structure = fx.read_bridge(client, bridge["id"])
    assert structure["scour_status"] == "NOT_EVALUATED"
    assert structure["version"] == 1


def test_the_fully_licensed_engineer_finalises_and_the_cascade_runs(
    client, roster, bridge
):
    """
    The third engineer differs from the other two only in carrying both halves of the
    licence, and her identical request passes the gate and writes the banded status
    through to the structure.

    PRD §3.6: "**Hop 1** sets `status` to `FINAL` and stamps `finalized_at` from the
    logical clock."
    PRD §3.6: "writes the evaluation's `derived_scour_status` through to the structure's
    `scour_status`, recomputes the structure's `inspection_interval_months`"
    PRD §3.6: "That flag is false exactly when `scour_status` is `SCOUR_CRITICAL` and no
    plan of action for the structure is `APPROVED`, and true in every other case —
    including on structures that are `LOW_RISK`, `STABILIZED` or `NOT_EVALUATED`."

    Design: Corner/errors/scour_finalize_by_unlicensed_engineer_rejected
    """
    setup = _three_rating_engineers_each_with_a_draft_evaluation(client, roster, bridge)
    for label, person in (("Ulla Unlicensed", setup["ulla"]), ("Paul Pending", setup["paul"])):
        validate_error(
            client.finalize_scour_evaluation(
                setup["drafts"][label]["id"],
                make_rating_engineer_headers(person["id"]),
            ),
            e.ERR_RATING_ENGINEER_NOT_LICENSED,
            422,
        )

    finalised = validate_success(
        client.finalize_scour_evaluation(
            setup["drafts"]["Rita Rating"]["id"], roster.engineer_headers
        ),
        200,
    )

    assert finalised["status"] == "FINAL"
    a.assert_instant_equals(finalised["finalized_at"], c.BASE_CLOCK, "finalized_at")
    structure = fx.read_bridge(client, bridge["id"])
    assert structure["scour_status"] == "LOW_RISK"
    assert structure["poa_compliant"] is True
    assert structure["version"] == 2
    assert fx.plans_for_bridge(client, bridge["id"]) == []
