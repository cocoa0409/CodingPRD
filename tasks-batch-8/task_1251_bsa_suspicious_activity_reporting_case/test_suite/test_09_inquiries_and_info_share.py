"""Law-enforcement inquiries and 314(b) information sharing: safety hold vs
certification expiry, duplicate buffer, sweep expiry (PRD §2.5, §2.10, §3.7,
§3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_info_share,
    assert_same_instant,
    create_case,
    create_customer,
    create_info_share,
    create_le_inquiry,
    create_staff,
    link_inquiry_to_case,
    respond_and_close_inquiry,
    run_sweep,
    set_clock,
    validate_error,
    validate_success,
)

def _open_inquiry_with_share(api, staff):
    """Case OPEN + linked inquiry UNDER_REVIEW + DRAFT 314(b) share tied to the
    case, certified 2026-01-01 (expires 2027-01-01)."""
    customer = create_customer(staff)
    case = create_case(staff, customer["id"])
    inquiry = create_le_inquiry(staff, customer["id"], inquiry_reference="LE-9001")
    link_inquiry_to_case(staff, inquiry["id"], case["id"])
    share = create_info_share(staff, customer["id"], case_id=case["id"],
                              certified_at="2026-01-01T00:00:00Z")
    return customer, case, inquiry, share


def test_send_with_open_inquiry_and_expired_cert_returns_le_inquiry_open(api):
    """PRD §2.10: "Priority order, from highest to lowest, is:
    malformed-request checks (missing fields, bad enums, non-positive amounts,
    incoherent date windows, a QA review lacking exactly one target, or a
    duplicate active QA sample on the same target — all `ERR_INVALID_REQUEST`);
    then authentication (`ERR_UNAUTHENTICATED`); then role authorization
    (`ERR_FORBIDDEN_ROLE`); then segregation-of-duties
    (`ERR_SEGREGATION_OF_DUTIES`); then existence of every referenced id
    (`ERR_NOT_FOUND`); then state-machine legality (`ERR_INVALID_STATE`); then
    OCC stale-version (`ERR_STALE_VERSION`); then the law-enforcement-inquiry
    safety hold (`ERR_LE_INQUIRY_OPEN`); then the customer-prohibited gate
    (`ERR_CUSTOMER_PROHIBITED`); then the threshold-window overlap check
    (`ERR_THRESHOLD_WINDOW_OVERLAP`); then the SAR activity-window overlap
    check (`ERR_ACTIVITY_WINDOW_OVERLAP`); then the 314(b) duplicate-window
    check (`ERR_314B_DUPLICATE_WINDOW`); then narrative length
    (`ERR_NARRATIVE_INSUFFICIENT`); then analyst capacity
    (`ERR_ANALYST_AT_CAPACITY`); then scenario retirement blocked by open
    alerts (`ERR_SCENARIO_HAS_OPEN_ALERTS`); then QA quota
    (`ERR_QA_QUOTA_EXCEEDED`); then filing deadline
    (`ERR_FILING_DEADLINE_PASSED`); then 314(b) certification expiry
    (`ERR_CERTIFICATION_EXPIRED`); then subject mismatch across a link
    (`ERR_SUBJECT_MISMATCH`); then the no-active-threshold check
    (`ERR_NO_ACTIVE_THRESHOLD`); and finally the scenario-not-active check
    (`ERR_SCENARIO_NOT_ACTIVE`)."
    PRD §3.8: "If the share names a `case_id`, no law-enforcement inquiry on
    that case may be open (else `ERR_LE_INQUIRY_OPEN`)."

    With the linked inquiry still open AND the certification expired (clock at
    2027-01-02, past the 2027-01-01 expiry), the safety hold outranks the
    temporal failure.

    Design: Difficulty/priority_pair_validation_conflict/send_314b_safety_beats_temporal
    """
    staff = create_staff()
    _customer, _case, _inquiry, share = _open_inquiry_with_share(api, staff)
    set_clock(staff, "2027-01-02T00:00:00Z")  # certification expired; inquiry open

    res = api.send_info_share(share["id"], staff.analyst)
    validate_error(res, ApiErrorId.ERR_LE_INQUIRY_OPEN)
    assert res.status_code == 409, (
        "safety (priority 8) outranks temporal (priority 18): the response "
        "must be 409 ERR_LE_INQUIRY_OPEN, not 422 ERR_CERTIFICATION_EXPIRED"
    )
    after = validate_success(api.get_info_share(share["id"], staff.analyst), 200)
    assert after["status"] == "DRAFT"
    assert after["sent_at"] is None


def test_send_after_inquiry_closed_returns_certification_expired(api):
    """PRD §3.8: "The logical clock must not be past `certification_expires_at`
    (else `ERR_CERTIFICATION_EXPIRED`)."

    Once the inquiry is responded and closed, the safety hold lifts and the
    same send now surfaces the temporal failure that was masked behind it.

    Design: Difficulty/priority_pair_validation_conflict/send_314b_safety_beats_temporal
    """
    staff = create_staff()
    _customer, _case, inquiry, share = _open_inquiry_with_share(api, staff)
    set_clock(staff, "2027-01-02T00:00:00Z")
    respond_and_close_inquiry(staff, inquiry["id"])

    res = api.send_info_share(share["id"], staff.analyst)
    validate_error(res, ApiErrorId.ERR_CERTIFICATION_EXPIRED)
    assert res.status_code == 422
    after = validate_success(api.get_info_share(share["id"], staff.analyst), 200)
    assert after["status"] == "DRAFT"
    assert after["sent_at"] is None


def test_send_with_expired_certification_rejected(api):
    """PRD §3.8: "The record starts in `DRAFT` with `certification_expires_at`
    computed as `certified_at` plus 365 days."
    PRD §3.8: "The logical clock must not be past `certification_expires_at`
    (else `ERR_CERTIFICATION_EXPIRED`)."

    Certified 2026-01-01 -> expires 2027-01-01T00:00:00Z; a send at
    2027-01-02 is past expiry.

    Design: Corner/complexity_layers/send_314b_certification_expired_rejected
    """
    staff = create_staff()
    customer = create_customer(staff)
    share = create_info_share(staff, customer["id"],
                              certified_at="2026-01-01T00:00:00Z")
    assert_info_share(share)
    assert_same_instant(share["certification_expires_at"], "2027-01-01T00:00:00Z",
                        "computed at creation as certified_at + 365 days")

    set_clock(staff, "2027-01-02T00:00:00Z")
    res = api.send_info_share(share["id"], staff.analyst)
    validate_error(res, ApiErrorId.ERR_CERTIFICATION_EXPIRED)
    assert res.status_code == 422
    after = validate_success(api.get_info_share(share["id"], staff.analyst), 200)
    assert after["status"] == "DRAFT"
    assert after["sent_at"] is None


def test_duplicate_outbound_share_within_90_days_rejected(api):
    """PRD §3.8: "an `OUTBOUND` share must not duplicate another `OUTBOUND`
    share to the same counterparty about the same subject that was already
    sent within the trailing closed 90-day buffer — counting only prior shares
    in `SENT` or `RESPONDED` — else `ERR_314B_DUPLICATE_WINDOW`."

    Design: Corner/errors/duplicate_314b_send_within_buffer_rejected
    """
    staff = create_staff()
    customer = create_customer(staff)
    first = create_info_share(staff, customer["id"],
                              counterparty_institution_id="INST-9",
                              purpose_note="Initial coordination")
    sent = validate_success(api.send_info_share(first["id"], staff.analyst), 200)
    assert sent["status"] == "SENT"
    duplicate = create_info_share(staff, customer["id"],
                                  counterparty_institution_id="INST-9",
                                  purpose_note="Duplicate to same counterparty")
    other_counterparty = create_info_share(staff, customer["id"],
                                           counterparty_institution_id="INST-10",
                                           purpose_note="Different counterparty")
    set_clock(staff, "2026-05-20T00:00:00Z")  # 19 days later: inside the buffer

    res = api.send_info_share(duplicate["id"], staff.analyst)
    validate_error(res, ApiErrorId.ERR_314B_DUPLICATE_WINDOW)
    assert res.status_code == 409
    dup_after = validate_success(api.get_info_share(duplicate["id"], staff.analyst), 200)
    assert dup_after["status"] == "DRAFT"

    other = validate_success(
        api.send_info_share(other_counterparty["id"], staff.analyst), 200)
    assert other["status"] == "SENT", "a different counterparty is not a duplicate"
    assert_same_instant(other["sent_at"], "2026-05-20T00:00:00Z")


def test_unanswered_share_expires_after_30_days(api):
    """PRD §2.5: "it expires every `InfoShareRequest` whose status is `SENT`,
    whose `sent_at` is more than 30 days in the past, and which has not
    received a response, moving it to `EXPIRED`."

    At exactly sent_at + 30 days the share is still SENT ("more than" is
    strict); one second later the sweep expires it.

    Design: Corner/complexity_layers/share_expires_after_30_days_sweep
    """
    staff = create_staff()
    customer = create_customer(staff)
    share = create_info_share(staff, customer["id"])
    sent = validate_success(api.send_info_share(share["id"], staff.analyst), 200)
    assert_same_instant(sent["sent_at"], "2026-05-01T00:00:00Z", "sent at the default clock")

    set_clock(staff, "2026-05-31T00:00:00Z")  # exactly sent_at + 30 days
    sweep = run_sweep(staff)
    assert sweep["shares_expired"] == 0
    mid = validate_success(api.get_info_share(share["id"], staff.analyst), 200)
    assert mid["status"] == "SENT"

    set_clock(staff, "2026-05-31T00:00:01Z")  # 30 days + 1 second
    sweep = run_sweep(staff)
    assert sweep["shares_expired"] == 1
    end = validate_success(api.get_info_share(share["id"], staff.analyst), 200)
    assert end["status"] == "EXPIRED"
