"""Payload factories -- one per resource, carrying input fields only."""

DEFAULTS = {
    "ACCOUNT_NAME": "Northwind Mailers",
    "CAMPAIGN_NAME": "Spring 2026",
    "STYLE_NAME": "Casual Script",
    "TEMPLATE_NAME": "Spring Note",
    "TEMPLATE_BODY": "Thank you kindly",
    "TEMPLATE_CHARACTER_COUNT": 400,
    "LIST_NAME": "Spring List",
    "CHARS_PER_MINUTE": 4000,
    "INK_UL_PER_1000_CHARS": 4.0,
    "MACHINE_CAPACITY_MINUTES": 480,
    "INK_LOT_VOLUME_UL": 20000,
    "SEED_ESCROW_CENTS": 500000,
}


def account_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["ACCOUNT_NAME"], "permit_number": "PMT-100"}
    payload.update(overrides)
    return payload


def postage_topup_payload(**overrides) -> dict:
    payload = {"amount_cents": DEFAULTS["SEED_ESCROW_CENTS"], "reason": "seed escrow"}
    payload.update(overrides)
    return payload


def blackout_date_payload(**overrides) -> dict:
    payload = {"blackout_date": "2026-06-05", "reason": "carrier holiday"}
    payload.update(overrides)
    return payload


def handwriting_style_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["STYLE_NAME"],
        "pen_type": "GEL",
        "ink_type": "INK_BLUE_A",
        "chars_per_minute": DEFAULTS["CHARS_PER_MINUTE"],
        "ink_ul_per_1000_chars": DEFAULTS["INK_UL_PER_1000_CHARS"],
    }
    payload.update(overrides)
    return payload


def machine_payload(**overrides) -> dict:
    payload = {
        "machine_code": "SLOT-BIG",
        "daily_capacity_minutes": DEFAULTS["MACHINE_CAPACITY_MINUTES"],
    }
    payload.update(overrides)
    return payload


def ink_lot_payload(**overrides) -> dict:
    payload = {
        "lot_code": "LOT-A",
        "ink_type": "INK_BLUE_A",
        "initial_volume_ul": DEFAULTS["INK_LOT_VOLUME_UL"],
    }
    payload.update(overrides)
    return payload


def campaign_payload(account_id, **overrides) -> dict:
    payload = {"account_id": account_id, "name": DEFAULTS["CAMPAIGN_NAME"]}
    payload.update(overrides)
    return payload


def template_payload(account_id, handwriting_style_id, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "handwriting_style_id": handwriting_style_id,
        "name": DEFAULTS["TEMPLATE_NAME"],
        "body_text": DEFAULTS["TEMPLATE_BODY"],
        "character_count": DEFAULTS["TEMPLATE_CHARACTER_COUNT"],
    }
    payload.update(overrides)
    return payload


def mailing_list_payload(account_id, **overrides) -> dict:
    payload = {"account_id": account_id, "name": DEFAULTS["LIST_NAME"]}
    payload.update(overrides)
    return payload


def list_record_payload(**overrides) -> dict:
    payload = {
        "first_name": "Bob",
        "last_name": "Jones",
        "address_line1": "200 Oak Ave",
        "city": "Chicago",
        "state_code": "IL",
        "zip5": "60602",
        "dpv_confirmation_code": "Y",
    }
    payload.update(overrides)
    return payload


def mail_job_payload(campaign_id, template_id, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "template_id": template_id,
        "job_kind": "ADDRESSED",
        "mail_class": "MARKETING_MAIL",
    }
    payload.update(overrides)
    return payload


def eddm_route_payload(**overrides) -> dict:
    payload = {
        "route_code": "C001",
        "total_deliveries": 6,
        "residential_piece_count": 4,
        "business_piece_count": 2,
    }
    payload.update(overrides)
    return payload


def proof_payload(mail_job_id, template_id, **overrides) -> dict:
    payload = {"mail_job_id": mail_job_id, "template_id": template_id}
    payload.update(overrides)
    return payload


def production_run_payload(machine_id, ink_lot_id, expected_mail_job_version, **overrides) -> dict:
    payload = {
        "machine_id": machine_id,
        "ink_lot_id": ink_lot_id,
        "run_date": "2026-06-05",
        "piece_count": 1,
        "capacity_variant": "SINGLE_PASS",
        "expected_mail_job_version": expected_mail_job_version,
    }
    payload.update(overrides)
    return payload


def drip_schedule_payload(campaign_id, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "name": "Spring Drip",
        "anchor_variant": "ANCHOR_IN_HOME",
    }
    payload.update(overrides)
    return payload


def drip_step_payload(mail_job_id, sequence_no, anchor_date, expected_drip_schedule_version, **overrides) -> dict:
    payload = {
        "mail_job_id": mail_job_id,
        "sequence_no": sequence_no,
        "anchor_date": anchor_date,
        "expected_drip_schedule_version": expected_drip_schedule_version,
    }
    payload.update(overrides)
    return payload


def reprint_request_payload(list_record_id, return_event_id, campaign_id, expected_list_record_version, **overrides) -> dict:
    payload = {
        "list_record_id": list_record_id,
        "return_event_id": return_event_id,
        "campaign_id": campaign_id,
        "expected_list_record_version": expected_list_record_version,
    }
    payload.update(overrides)
    return payload


def ncoa_move_payload(new_address_line1, **overrides) -> dict:
    payload = {"new_address_line1": new_address_line1}
    payload.update(overrides)
    return payload


def return_payload(**overrides) -> dict:
    payload = {"return_reason": "VACANT"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Named recipient rosters used across the suite.
#
# NOTE on the mutual exclusivity of the unmailable and duplicate buckets: every
# roster below is built so that no record is simultaneously UNMAILABLE-tier and
# a screening duplicate.  The only non-mailable records (Gus, DPV "N") carry a
# family name, street line and postal code shared with nobody, so they survive
# both EXACT and HOUSEHOLD screening as their own group's first member.
# --------------------------------------------------------------------------
JOHN_SMITH = dict(
    first_name="John", last_name="Smith", address_line1="100 Main St",
    city="Chicago", state_code="IL", zip5="60601", dpv_confirmation_code="Y",
)
JANE_SMITH = dict(
    first_name="Jane", last_name="Smith", address_line1="100 Main St",
    city="Chicago", state_code="IL", zip5="60601", dpv_confirmation_code="Y",
)
BOB_JONES = dict(
    first_name="Bob", last_name="Jones", address_line1="200 Oak Ave",
    city="Chicago", state_code="IL", zip5="60602", dpv_confirmation_code="Y",
)
CARL_LEE = dict(
    first_name="Carl", last_name="Lee", address_line1="300 Pine Rd",
    city="Chicago", state_code="IL", zip5="60603", dpv_confirmation_code="Y",
)
DANA_FOX = dict(
    first_name="Dana", last_name="Fox", address_line1="400 Elm St",
    city="Chicago", state_code="IL", zip5="60604", dpv_confirmation_code="Y",
)
EVE_RAY = dict(
    first_name="Eve", last_name="Ray", address_line1="500 Ash Ln",
    city="Chicago", state_code="IL", zip5="60605", dpv_confirmation_code="Y",
)
FRANK_ASH = dict(
    first_name="Frank", last_name="Ash", address_line1="600 Bay Dr",
    city="Chicago", state_code="IL", zip5="60606", dpv_confirmation_code="D",
)
GIL_NYE = dict(
    first_name="Gil", last_name="Nye", address_line1="700 Fir Ct",
    city="Chicago", state_code="IL", zip5="60607", dpv_confirmation_code="Y",
)
HAL_ODE = dict(
    first_name="Hal", last_name="Ode", address_line1="800 Gum Way",
    city="Chicago", state_code="IL", zip5="60608", dpv_confirmation_code="Y",
)
GUS_VALE = dict(
    first_name="Gus", last_name="Vale", address_line1="900 Ivy Pl",
    city="Chicago", state_code="IL", zip5="60609", dpv_confirmation_code="N",
)

# Six DPV "Y" records plus one DPV "D" record.  The Smith pair shares a
# household key but not an exact key.
SEVEN_RECORD_ROSTER = [
    JOHN_SMITH, JANE_SMITH, BOB_JONES, CARL_LEE, DANA_FOX, EVE_RAY, FRANK_ASH,
]

# The seven above plus one DPV "N" record whose keys collide with nothing.
EIGHT_RECORD_ROSTER = SEVEN_RECORD_ROSTER + [GUS_VALE]

# Six DPV "Y" records with six distinct household keys.
SIX_AUTOMATION_ROSTER = [BOB_JONES, CARL_LEE, DANA_FOX, EVE_RAY, GIL_NYE, HAL_ODE]

# One DPV "Y" record.
SINGLE_RECORD_ROSTER = [BOB_JONES]
