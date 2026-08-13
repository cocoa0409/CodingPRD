"""Notices of intent: filing lifecycle, refile cycle, and uniqueness."""
from test_helpers import (
    ApiErrorId,
    assert_notice,
    create_notice_payload,
    create_open_year,
    get_success_data,
    make_parent_headers,
    setup_registered_enrollment,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]


def _setup_notice(api):
    year = create_open_year()
    ctx = setup_registered_enrollment(year["id"], 4, family_name="Fam Noi",
                                      district_code="D-34")
    notice = get_success_data(
        api.create_notice(ctx["enrollment"]["id"], create_notice_payload(district_code="D-34"),
                          ctx["parent_headers"])
    )
    return ctx, notice


def test_notice_full_lifecycle_with_refile_cycle(api):
    """PRD §3.3: "From there the `Registrar` either acknowledges it — `FILED` →
    `ACKNOWLEDGED`, stamping `acknowledged_at` — or returns it, `FILED` →
    `RETURNED`, recording the supplied `returned_reason`."
    PRD §3.3: "A returned notice is not the end: the parent refiles it, moving
    `RETURNED` → `FILED`, which refreshes `filed_at`, clears `returned_reason` to
    null, and increments `refile_count`; each filing also increments the notice's
    `version`."

    Design: Corner/state_machines/notice_full_lifecycle_with_refile_cycle
    """
    ctx, notice = _setup_notice(api)
    parent = ctx["parent_headers"]

    filed = validate_success(api.file_notice(notice["id"], parent))
    assert_notice(filed)
    assert filed["status"] == "FILED"
    assert filed["refile_count"] == 0
    assert filed["filed_at"] is not None

    returned = validate_success(
        api.return_notice(notice["id"], {"returned_reason": "missing signature page"}, REGISTRAR)
    )
    assert returned["status"] == "RETURNED"
    assert returned["returned_reason"] == "missing signature page"

    refiled = validate_success(api.file_notice(notice["id"], parent))
    assert refiled["status"] == "FILED"
    assert refiled["refile_count"] == 1
    assert refiled["returned_reason"] is None

    acknowledged = validate_success(api.acknowledge_notice(notice["id"], REGISTRAR))
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["acknowledged_at"] is not None

    # Filing again from ACKNOWLEDGED is not a defined transition.
    resp = api.file_notice(notice["id"], parent)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_notice_acknowledge_from_draft_rejected(api):
    """PRD §3.3: "From there the `Registrar` either acknowledges it — `FILED` →
    `ACKNOWLEDGED`, stamping `acknowledged_at` — or returns it, `FILED` →
    `RETURNED`, recording the supplied `returned_reason`."
    PRD §2.8: "State feasibility: the target resource's current state must permit
    the operation."

    Design: Corner/state_machines/notice_acknowledge_from_draft_rejected
    """
    ctx, notice = _setup_notice(api)
    resp = api.acknowledge_notice(notice["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    current = get_success_data(api.get_notice(notice["id"], REGISTRAR))
    assert current["status"] == "DRAFT"


def test_second_notice_rejected(api):
    """PRD §3.3: "only one open notice may exist per enrollment — a notice
    standing in `DRAFT`, `FILED`, or `RETURNED` blocks the creation of another
    with `ERR_NOTICE_ALREADY_OPEN`."

    Design: Corner/errors/second_notice_rejected
    """
    ctx, _notice = _setup_notice(api)
    resp = api.create_notice(
        ctx["enrollment"]["id"], create_notice_payload(district_code="D-34"),
        ctx["parent_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NOTICE_ALREADY_OPEN)
