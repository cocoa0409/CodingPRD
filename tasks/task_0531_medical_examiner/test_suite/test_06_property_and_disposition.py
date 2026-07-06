"""Body release gating, property release approval/deny, indigent disposition."""
from test_helpers import (
    validate_success, validate_error,
    create_investigator, create_pathologist, create_cooler,
    create_investigating_case, store_body,
    add_property_item, add_next_of_kin, request_property_release,
    declare_indigent, setup_certified_case_natural,
    make_investigator_headers, make_medical_examiner_headers,
)


def test_body_release_requires_case_certified(api):
    """PRD §3.3: "Release is permitted only while release_blocked is false; an attempt to
    release a still-blocked body is rejected with ERR_RELEASE_BLOCKED (HTTP 409)." PRD §3.3:
    "and release_blocked is set to true — a body may not be released until its case reaches
    certification or an indigent path opens."

    Design: Difficulty/cross_entity_state_dependency/body_release_requires_case_certified
    """
    inv = create_investigator("Inv N")
    cooler = create_cooler(slot_capacity=3)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    body = store_body(inv, body, cooler)  # release_blocked = true, case still INVESTIGATING

    inv_headers = make_investigator_headers(inv["id"])
    res = api.release_body(body["id"], inv_headers)
    validate_error(res, "ERR_RELEASE_BLOCKED", expected_status=409)


def test_request_then_deny_conserves_held_property_count(api):
    """PRD §3.7: "Alternatively a requested release may be denied, moving it REQUESTED ->
    DENIED." PRD §3.7: "every property item for the case still in HELD is flipped to RELEASED,
    and the count of items so flipped is recorded on the release as released_item_count; the
    release's version increments."

    Design: Difficulty/compensating_invariant/request_then_deny_conserves_held_property_count
    """
    inv = create_investigator("Inv R")
    case, body = create_investigating_case(inv, case_type="NATURAL")
    item1 = add_property_item(inv, case, "phone", 20000)
    item2 = add_property_item(inv, case, "keys", 1000)
    kin = add_next_of_kin(inv, case, "Kin R", "SPOUSE")
    release = request_property_release(inv, case, kin)

    inv_headers = make_investigator_headers(inv["id"])
    denied = validate_success(api.deny_property_release(release["id"], inv_headers), 200)
    assert denied["release_status"] == "DENIED"

    i1 = validate_success(api.get_property_item(item1["id"], inv_headers), 200)
    i2 = validate_success(api.get_property_item(item2["id"], inv_headers), 200)
    assert i1["item_status"] == "HELD"
    assert i2["item_status"] == "HELD"


def test_first_body_bubbles_case_to_investigating(api):
    """PRD §3.3: "Intaking the first body is the event that advances the case ACCEPTED ->
    INVESTIGATING, and both the new body and the parent case's version increment as a result."

    Design: Corner/state_machines/first_body_bubbles_case_to_investigating
    """
    inv = create_investigator("Inv CS5")
    inv_headers = make_investigator_headers(inv["id"])
    from test_helpers import create_accepted_case, create_body_payload
    case = create_accepted_case(inv, case_type="NATURAL")
    assert case["status"] == "ACCEPTED"

    validate_success(
        api.create_body(case["id"], create_body_payload(tag_no="CS-T5"), inv_headers), 201
    )
    case_after = validate_success(api.get_case(case["id"], inv_headers), 200)
    assert case_after["status"] == "INVESTIGATING"


def test_property_release_approve_cascade_releases_items(api):
    """PRD §3.7: "On approval the release records the approver_user_id, sets release_status to
    APPROVED, and cascades — every property item for the case still in HELD is flipped to
    RELEASED, and the count of items so flipped is recorded on the release as
    released_item_count; the release's version increments."

    Design: Corner/state_machines/property_release_approve_cascade_releases_items
    """
    inv = create_investigator("Inv CS7")
    inv2 = create_investigator("Inv CS7b")
    me = create_pathologist("ME CS7", is_medical_examiner=True)
    # Certify the case first so approval's CERTIFIED precondition holds.
    case, body = create_investigating_case(inv, case_type="NATURAL")
    item1 = add_property_item(inv, case, "phone", 20000)
    item2 = add_property_item(inv, case, "cash", 8000)
    kin = add_next_of_kin(inv, case, "Kin CS7", "SPOUSE", verify=True)
    from test_helpers import draft_certificate, sign_certificate
    cert = draft_certificate(me, case, manner_of_death="NATURAL")
    sign_certificate(me, case["id"], cert["id"])
    release = request_property_release(inv, case, kin)

    inv2_headers = make_investigator_headers(inv2["id"])
    approved = validate_success(api.approve_property_release(release["id"], inv2_headers), 200)
    assert approved["release_status"] == "APPROVED"
    assert approved["released_item_count"] == 2

    inv_headers = make_investigator_headers(inv["id"])
    i1 = validate_success(api.get_property_item(item1["id"], inv_headers), 200)
    i2 = validate_success(api.get_property_item(item2["id"], inv_headers), 200)
    assert i1["item_status"] == "RELEASED"
    assert i2["item_status"] == "RELEASED"


def test_property_release_kin_unverified_alone_returns_409(api):
    """PRD §3.7: "The referenced next-of-kin must have verified true, or the approval is
    rejected with ERR_KIN_UNVERIFIED (HTTP 409)."

    Design: Corner/validations/property_release_kin_unverified_alone_returns_409
    """
    inv = create_investigator("Inv CV4")
    inv2 = create_investigator("Inv CV4b")
    me = create_pathologist("ME CV4", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    add_property_item(inv, case, "hat", 500)
    kin = add_next_of_kin(inv, case, "Kin CV4", "PARENT", verify=False)  # UNVERIFIED
    from test_helpers import draft_certificate, sign_certificate
    cert = draft_certificate(me, case, manner_of_death="NATURAL")
    sign_certificate(me, case["id"], cert["id"])
    release = request_property_release(inv, case, kin)

    inv2_headers = make_investigator_headers(inv2["id"])
    res = api.approve_property_release(release["id"], inv2_headers)
    validate_error(res, "ERR_KIN_UNVERIFIED", expected_status=409)


def test_property_release_lead_investigator_cannot_approve(api):
    """PRD §2.11: "the investigator who approves a property release must not be the lead
    investigator recorded on the case — an approval where the acting investigator's identity
    equals the case's lead is rejected with the same ERR_SEGREGATION_VIOLATION (HTTP 403)."

    Design: Corner/rbac/segregation_release_lead_cannot_approve
    """
    inv = create_investigator("Inv CR4")
    me = create_pathologist("ME CR4", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    add_property_item(inv, case, "belt", 500)
    kin = add_next_of_kin(inv, case, "Kin CR4", "SIBLING", verify=True)
    from test_helpers import draft_certificate, sign_certificate
    cert = draft_certificate(me, case, manner_of_death="NATURAL")
    sign_certificate(me, case["id"], cert["id"])
    release = request_property_release(inv, case, kin)

    # The lead investigator attempts approval.
    inv_headers = make_investigator_headers(inv["id"])
    res = api.approve_property_release(release["id"], inv_headers)
    validate_error(res, "ERR_SEGREGATION_VIOLATION", expected_status=403)


def test_indigent_approve_with_verified_kin_rejected(api):
    """PRD §3.8: "but only when the case has no claiming kin — that is, no next-of-kin for the
    case has verified true; if any verified kin exists the approval is rejected with
    ERR_KIN_CLAIMANT_EXISTS (HTTP 409)."

    Design: Corner/validations/indigent_approve_with_verified_kin_rejected
    """
    inv = create_investigator("Inv CV2")
    me = create_pathologist("ME CV2", is_medical_examiner=True)
    case, body = create_investigating_case(inv, case_type="NATURAL")
    add_next_of_kin(inv, case, "Kin CV2", "CHILD", verify=True)
    disp = declare_indigent(inv, case, statutory_allowance_cents=400000, itemized_cost_cents=100000)

    me_headers = make_medical_examiner_headers(me["id"])
    res = api.approve_indigent_disposition(disp["id"], me_headers)
    validate_error(res, "ERR_KIN_CLAIMANT_EXISTS", expected_status=409)


def test_indigent_bury_escheats_remaining_held_property(api):
    """PRD §3.8: "Burial cascades a final settlement of the estate: every property item for
    the case still in `HELD` is escheated to the state, flipping its `item_status` to
    `ESCHEATED`, and the disposition's `version` increments."

    Design: Corner/state_machines/indigent_bury_escheats_remaining_held_property
    """
    inv = create_investigator("Inv CS6")
    me = create_pathologist("ME CS6", is_medical_examiner=True)
    cooler = create_cooler(slot_capacity=2)
    case, body = create_investigating_case(inv, case_type="NATURAL", decedent_name="Unknown CS6")
    body = store_body(inv, body, cooler)
    item = add_property_item(inv, case, "coat", 3000)
    disp = declare_indigent(inv, case, statutory_allowance_cents=400000, itemized_cost_cents=100000)

    me_headers = make_medical_examiner_headers(me["id"])
    validate_success(api.approve_indigent_disposition(disp["id"], me_headers), 200)  # clears release_blocked

    inv_headers = make_investigator_headers(inv["id"])
    validate_success(api.release_body(body["id"], inv_headers), 200)
    buried = validate_success(api.bury_indigent_disposition(disp["id"], inv_headers), 200)
    assert buried["disposition_status"] == "BURIED"

    item_after = validate_success(api.get_property_item(item["id"], inv_headers), 200)
    assert item_after["item_status"] == "ESCHEATED"
