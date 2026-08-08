"""Impression capture, the three-band quality review, and the retake ladder."""

from test_helpers import (
    ApiErrorId,
    assert_impression_record,
    fixtures as fx,
    review_impression_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _arch_in_impression_pending(name, dob, phone, arch_position="MAXILLARY"):
    """A flexible-partial arch driven to IMPRESSION_PENDING with nothing captured."""
    ctx = fx.setup_case_past_exam(
        arch_position=arch_position,
        patient_overrides={"full_name": name, "date_of_birth": dob, "phone": phone},
    )
    fx.start_fabrication(ctx["arch"]["id"])
    return ctx


class TestQualityBandBoundary:
    def test_score_of_exactly_85_lands_in_the_accepted_band(self, api, prosthodontist_headers):
        """PRD §3.3: "- A score of **85 or more** puts the record in `ACCEPTED`.
        `retake_required` stays false."
        PRD §3.3: "On `ACCEPTED`, the arch advances out of `IMPRESSION_PENDING` — to
        `MILESTONE_PENDING` when its `required_milestones` list is non-empty, with
        `next_required_milestone` set to the first entry of that list, or straight to
        `LAB_FABRICATION` when the list is empty, which holds only for an
        `IMMEDIATE_DENTURE`."

        Design: Difficulty/boundary_precision_check/impression_score_85_accepts_84_only_provisionally
        """
        ctx = _arch_in_impression_pending("Odile Praxmarer", "1956-11-11", "555-0366")
        impression = fx.capture_impression(ctx["arch"]["id"], "DIGITAL_SCAN")

        reviewed = validate_success(
            api.review_impression(
                impression["id"], review_impression_payload(85), prosthodontist_headers
            ),
            200,
        )

        assert_impression_record(reviewed)
        assert reviewed["quality_status"] == "ACCEPTED", "85 is inclusive on the accept edge"
        assert reviewed["retake_required"] is False
        assert reviewed["quality_score"] == 85
        assert fx.read_arch(ctx["arch"]["id"])["arch_status"] == "MILESTONE_PENDING"

    def test_score_of_84_falls_to_the_provisional_band_and_leaves_the_arch_put(self, api, prosthodontist_headers):
        """PRD §3.3: "- A score of **at least 70 but below 85** puts the record in
        `PROVISIONAL_ACCEPTED` and sets `retake_required` to true."
        PRD §3.3: "On `PROVISIONAL_ACCEPTED` and on `REJECTED`, the arch is left
        exactly where it was, in `IMPRESSION_PENDING`, and the clinician's next move
        is a retake."

        Design: Difficulty/boundary_precision_check/impression_score_85_accepts_84_only_provisionally
        """
        ctx = _arch_in_impression_pending("Odile Praxmarer", "1956-11-11", "555-0366")
        impression = fx.capture_impression(ctx["arch"]["id"], "DIGITAL_SCAN")

        reviewed = validate_success(
            api.review_impression(
                impression["id"], review_impression_payload(84), prosthodontist_headers
            ),
            200,
        )

        assert reviewed["quality_status"] == "PROVISIONAL_ACCEPTED", "84 is one below the edge"
        assert reviewed["retake_required"] is True
        arch = fx.read_arch(ctx["arch"]["id"])
        assert arch["arch_status"] == "IMPRESSION_PENDING"
        assert arch["retake_count"] == 0, "reviewing does not consume a retake"


class TestRetakeLeg:
    def test_rejected_record_is_superseded_and_mints_a_successor(self, api, prosthodontist_headers):
        """PRD §3.3: "- A score **below 70** puts the record in `REJECTED` and
        likewise sets `retake_required` to true."
        PRD §3.3: "When it is allowed, four things happen together: the arch's
        `retake_count` increases by one and its `version` increments by 1; a
        successor record is created on the same arch in `PENDING_REVIEW` with
        `attempt_number` one higher than the superseded record's and the
        `capture_method` supplied on the request; the superseded record's
        `quality_status` becomes `SUPERSEDED` and its `superseded_by_impression_id`
        is set to the successor's identifier; and the superseded record's `version`
        increments by 1."
        PRD §3.3: "**The response body is the superseded record, not the
        successor** — the successor is reachable by following
        `superseded_by_impression_id`, or by listing impression records filtered on
        `case_arch_id`, on `quality_status`, or on `superseded_by_impression_id`."

        Design: Corner/state_machines/impression_rejected_band_then_retake_supersedes_and_mints_successor
        """
        ctx = _arch_in_impression_pending("Kaya Trevino", "1961-12-12", "555-1009")
        first = fx.capture_impression(ctx["arch"]["id"], "PHYSICAL_IMPRESSION")

        reviewed = fx.review_impression(first["id"], 60)
        assert reviewed["quality_status"] == "REJECTED"
        assert reviewed["retake_required"] is True

        superseded = validate_success(
            api.request_retake(
                first["id"], {"capture_method": "DIGITAL_SCAN"}, prosthodontist_headers
            ),
            200,
        )
        assert superseded["id"] == first["id"], "the response body is the superseded record"
        assert superseded["quality_status"] == "SUPERSEDED"
        successor_id = superseded["superseded_by_impression_id"]
        assert successor_id is not None

        arch = fx.read_arch(ctx["arch"]["id"])
        assert arch["retake_count"] == 1
        assert arch["arch_status"] == "IMPRESSION_PENDING"

        successor = fx.read_impression(successor_id)
        assert successor["quality_status"] == "PENDING_REVIEW"
        assert successor["attempt_number"] == 2
        assert successor["capture_method"] == "DIGITAL_SCAN"

        rows, meta = validate_paginated(
            api.list_impressions(
                prosthodontist_headers,
                params={
                    "superseded_by_impression_id": successor_id, "limit": 10, "offset": 0,
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first["id"]

    def test_fourth_retake_on_the_same_arch_is_refused_by_the_ceiling(self, api, prosthodontist_headers):
        """PRD §3.3: "Before anything happens the arch's `retake_count` must be
        **strictly below 3**; at three retakes the arch is out of attempts and the
        request is refused with `ERR_RETAKE_LIMIT_EXCEEDED`."

        Design: Corner/state_machines/impression_retake_ceiling_blocks_the_fourth_retake
        """
        ctx = _arch_in_impression_pending("Lior Abadi", "1943-01-13", "555-1010")

        current = fx.capture_impression(ctx["arch"]["id"], "PHYSICAL_IMPRESSION")
        for _ in range(3):
            fx.review_impression(current["id"], 50)
            superseded = fx.request_retake(current["id"], "PHYSICAL_IMPRESSION")
            current = fx.read_impression(superseded["superseded_by_impression_id"])
        fx.review_impression(current["id"], 50)

        assert fx.read_arch(ctx["arch"]["id"])["retake_count"] == 3

        response = api.request_retake(
            current["id"], {"capture_method": "PHYSICAL_IMPRESSION"}, prosthodontist_headers
        )
        validate_error(response, ApiErrorId.ERR_RETAKE_LIMIT_EXCEEDED.value, 409)

        assert fx.read_arch(ctx["arch"]["id"])["retake_count"] == 3
        blocked = fx.read_impression(current["id"])
        assert blocked["quality_status"] == "REJECTED"
        assert blocked["superseded_by_impression_id"] is None

        _, meta = validate_paginated(
            api.list_impressions(
                prosthodontist_headers,
                params={"case_arch_id": ctx["arch"]["id"], "limit": 100, "offset": 0},
            )
        )
        assert meta["total_count"] == 4, "no fifth record is minted"
