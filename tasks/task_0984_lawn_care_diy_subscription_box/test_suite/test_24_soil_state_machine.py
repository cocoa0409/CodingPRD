"""Soil test kit state machine: resample cycle and transition guards (PRD 3.3)."""
import test_helpers as th

AGRONOMIST = th.TEST_USERS["agronomist_headers"]


def _setup_kit(api, email):
    customer = th.register_customer(email=email)
    lawn = th.create_lawn(customer)
    kit = th.order_soil_test(customer, lawn)
    return customer, kit


def test_soil_resample_cycle(api):
    """PRD 3.3: "An `outcome` of `REJECTED` instead records the supplied `rejection_reason`, increments `reship_count` by 1, sends a fresh kit, and cycles the kit back to `KIT_SHIPPED`. The resample loop — `SAMPLE_RETURNED` back to `KIT_SHIPPED` and forward again — is an allowed cycle and may repeat until a sample is successfully analyzed."

    Design: Corner/state_machines/soil_resample_cycle
    """
    customer, kit = _setup_kit(api, email="s1@x.com")
    headers = th.make_customer_headers(customer["id"])
    th.get_success_data(api.return_sample(kit["id"], headers))

    rejected = th.validate_success(
        api.post_lab_result(
            kit["id"],
            {"outcome": "REJECTED", "rejection_reason": "insufficient mass"},
            AGRONOMIST,
        )
    )
    assert rejected["status"] == "KIT_SHIPPED", "rejection cycles the kit back"
    assert rejected["reship_count"] == 1
    assert rejected["rejection_reason"] == "insufficient mass"

    # Second pass: return again and analyze cleanly.
    th.get_success_data(api.return_sample(kit["id"], headers))
    analyzed = th.validate_success(
        api.post_lab_result(kit["id"], th.lab_result_analyzed_payload(
            ph=6.4, nitrogen_ppm=22, phosphorus_ppm=14, potassium_ppm=75,
            organic_matter_pct=2.9), AGRONOMIST)
    )
    assert analyzed["status"] == "ANALYZED"


def test_soil_lab_result_requires_returned_sample(api):
    """PRD 3.3: "An Agronomist then posts the lab outcome. This requires the kit to be in `SAMPLE_RETURNED`, otherwise `ERR_SOIL_TEST_NOT_RETURNED` (HTTP 409)."

    Design: Corner/state_machines/soil_lab_result_requires_returned
    """
    _, kit = _setup_kit(api, email="s2@x.com")
    # Kit is still KIT_SHIPPED — the sample was never returned.
    th.validate_error(
        api.post_lab_result(kit["id"], th.lab_result_analyzed_payload(), AGRONOMIST),
        th.ApiErrorId.ERR_SOIL_TEST_NOT_RETURNED,
    )


def test_soil_return_sample_twice_rejected(api):
    """PRD 3.3: "When the customer mails the sample back and marks it returned, the kit moves from `KIT_SHIPPED` to `SAMPLE_RETURNED`; the kit must actually be in `KIT_SHIPPED` (`ERR_SOIL_TEST_NOT_SHIPPED`, HTTP 409), and the acting customer must own the kit's lawn (`ERR_OWNERSHIP_MISMATCH`)."

    Design: Corner/state_machines/soil_return_sample_twice_rejected
    """
    customer, kit = _setup_kit(api, email="s3@x.com")
    headers = th.make_customer_headers(customer["id"])
    th.get_success_data(api.return_sample(kit["id"], headers))

    # The trigger is not idempotent: a second return is a state error.
    th.validate_error(
        api.return_sample(kit["id"], headers),
        th.ApiErrorId.ERR_SOIL_TEST_NOT_SHIPPED,
    )
