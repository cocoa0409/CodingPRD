"""RBAC, ownership, segregation of duties, and list-endpoint behavior
(PRD §2.1, §2.3, §2.9, §4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    build_user_headers,
    create_ad_track,
    create_client,
    create_cleared_media,
    create_live_event,
    create_media,
    create_offer,
    create_stenographer,
    create_work_order,
    get_success_data,
    make_ad_producer_headers,
    make_client_headers,
    make_qc_headers,
    quote_order,
    set_clock,
    setup_in_production_order,
    setup_track_in_qc_queue,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import INTAKE, OPS, QC, SCHED

MONDAY = "2026-08-03T10:00:00Z"


class TestAuthentication:
    def test_create_client_missing_auth_headers(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`. A request missing either header, or carrying a role name
        outside the declared set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/rbac/create_client_missing_auth_headers
        """
        resp = api.create_client(
            {"name": "NoAuth", "compliance_standard": "INTERNAL"},
            headers={"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestExclusiveOperations:
    def test_roles_cannot_cross_exclusive_operations(self, api):
        """PRD §2.1: "A request whose role is not on the endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "A `ClientContact` confirms quotes, accepts deliveries, and
        files or reopens complaints on behalf of their own organization only."
        and "A `Scheduler` owns the live side of the house: events, the
        stenographer roster, offers, preemption, no-show marking, and air
        control." and "A `CaptionEditor` authors caption tracks and drives them
        from draft through conform".

        Design: Corner/rbac/roles_cannot_cross_exclusive_operations
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL")
        client = ctx["client"]
        steno = create_stenographer()
        # ClientContact may not create work orders.
        resp1 = api.create_work_order(
            {"client_id": client["id"], "media_asset_id": ctx["media"]["id"],
             "service_type": "CAPTIONS", "turnaround_tier": "STANDARD",
             "language": "en-US"},
            make_client_headers(client["id"]))
        validate_error(resp1, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        # Stenographer may not create live events.
        resp2 = api.create_live_event(
            {"client_id": client["id"], "title": "E", "channel_id": "CH1",
             "start_at": "2026-08-10T14:00:00Z", "end_at": "2026-08-10T15:00:00Z",
             "required_certification": "CERT_CBC"},
            build_user_headers(steno["id"], "Stenographer"))
        validate_error(resp2, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        # QCSpecialist may not author caption tracks.
        resp3 = api.create_caption_track(
            ctx["work_order"]["id"],
            {"language": "en-US", "caption_format": "SRT",
             "speaker_id_style": "DASH",
             "expected_work_order_version": ctx["work_order"]["version"]},
            make_qc_headers("qc-1"))
        validate_error(resp3, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


class TestOwnership:
    def test_ownership_denied_cross_client_and_steno(self, api):
        """PRD §2.1: "When `X-User-Role` is `ClientContact`, `X-User-ID` is the
        `id` of the acting `Client`; ownership checks on any resource that
        references a `Client` compare the resource's `client_id` field to
        `X-User-ID`. When `X-User-Role` is `Stenographer`, `X-User-ID` is the
        `id` of the acting `Stenographer`; ownership checks on a
        `LiveAssignment` compare the assignment's `stenographer_id` to
        `X-User-ID`."

        Design: Corner/rbac/ownership_denied_cross_client_and_steno
        """
        set_clock(MONDAY)
        client_a = create_client(name="A", compliance_standard="INTERNAL")
        client_b = create_client(name="B", compliance_standard="INTERNAL")
        media_b = create_cleared_media(client_b["id"])
        wo_b = create_work_order(client_b["id"], media_b["id"])
        quote_order(wo_b["id"])
        # Client A confirming B's order -> forbidden.
        resp1 = api.confirm_work_order(wo_b["id"], make_client_headers(client_a["id"]))
        validate_error(resp1, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        after = validate_success(api.get_work_order(wo_b["id"], OPS))
        assert after["order_status"] == "QUOTED"

        s1 = create_stenographer(display_name="S1")
        s2 = create_stenographer(display_name="S2",
                                 certified_since="2021-01-01T00:00:00Z")
        ev = create_live_event(client_b["id"])
        offer = create_offer(ev["id"], s2["id"])
        # S1 accepting S2's offer -> forbidden.
        resp2 = api.accept_assignment(
            offer["id"], build_user_headers(s1["id"], "Stenographer"))
        validate_error(resp2, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        asg = validate_success(api.get_assignment(offer["id"], SCHED))
        assert asg["assignment_status"] == "OFFERED"


class TestSegregationOfDuties:
    def test_sod_reviewer_is_author_rejected(self, api):
        """PRD §2.9: "The user finalizing a QC review must differ from the
        track's `author_user_id`; the user approving an AD script or mix must
        differ from the AD track's `author_user_id`; and the user resolving a
        complaint must differ from the disputed track's `author_user_id`. Each
        violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/sod_reviewer_is_author_rejected
        """
        set_clock(MONDAY)
        # Caption leg: track authored by editor-1 sits in QC_QUEUED.
        ctx_c = setup_track_in_qc_queue(compliance_standard="INTERNAL")
        resp1 = api.create_qc_review(
            ctx_c["track"]["id"],
            {"review_mode": "FULL_REVIEW", "total_words": 10000,
             "minor_errors": 0, "major_errors": 0, "critical_errors": 0},
            make_qc_headers("editor-1"))  # same user id as the author
        validate_error(resp1, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        track = validate_success(api.get_caption_track(ctx_c["track"]["id"], QC))
        assert track["track_status"] == "QC_QUEUED"

        # AD leg: AD track authored by ad-1 sits in SCRIPT_REVIEW.
        ctx_a = setup_in_production_order(compliance_standard="INTERNAL",
                                          service_type="AUDIO_DESCRIPTION",
                                          frame_rate="FPS_25", client_name="AD Co")
        ad = create_ad_track(ctx_a["work_order"]["id"], author="ad-1",
                             gaps=[{"start_ms": 1000, "end_ms": 21000}],
                             segments=[{"gap_index": 0, "duration_ms": 10000,
                                        "text": "d"}])
        get_success_data(api.submit_script(ad["id"], make_ad_producer_headers("ad-1")))
        resp2 = api.approve_script(ad["id"], make_qc_headers("ad-1"))
        validate_error(resp2, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        ad_after = validate_success(api.get_ad_track(ad["id"], OPS))
        assert ad_after["ad_status"] == "SCRIPT_REVIEW"


class TestListEndpoints:
    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept two query parameters, `limit` and
        `offset`. The `limit` defaults to 10, must be at least 1, and may not
        exceed 100. The `offset` defaults to 0. Every list response orders its
        items by `created_at` ascending, and its `meta` object carries the
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_envelope
        """
        for name, std in (("C1", "INTERNAL"), ("C2", "SECTION_508"),
                          ("C3", "FCC_BROADCAST")):
            create_client(name=name, compliance_standard=std)
        page1, meta1 = validate_paginated(
            api.list_clients(INTAKE, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_clients(INTAKE, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        _, meta_default = validate_paginated(api.list_clients(INTAKE))
        assert meta_default["limit"] == 10

    def test_list_filter_combination(self, api):
        """PRD §4: "Every list endpoint paginates per §2.3 and filters by the
        query parameters named in §3."
        PRD §4 (work orders): "List work orders (filterable by `client_id`,
        `media_asset_id`, `order_status`)".

        Design: Corner/endpoints/list_filter_combination
        """
        set_clock(MONDAY)
        client_a = create_client(name="A", compliance_standard="INTERNAL")
        client_b = create_client(name="B", compliance_standard="INTERNAL")
        m_a1 = create_media(client_a["id"], title="A1", duration_seconds=600)
        m_a2 = create_media(client_a["id"], title="A2", duration_seconds=600)
        m_b1 = create_media(client_b["id"], title="B1", duration_seconds=600)
        wo_a1 = create_work_order(client_a["id"], m_a1["id"],
                                  turnaround_tier="STANDARD")
        wo_a2 = create_work_order(client_a["id"], m_a2["id"],
                                  turnaround_tier="RUSH")
        quote_order(wo_a2["id"])
        create_work_order(client_b["id"], m_b1["id"])

        data, meta = validate_paginated(api.list_work_orders(
            OPS, params={"client_id": client_a["id"], "order_status": "DRAFT"}))
        assert meta["total_count"] == 1
        assert len(data) == 1 and data[0]["id"] == wo_a1["id"]

        data2, meta2 = validate_paginated(api.list_work_orders(
            OPS, params={"client_id": client_a["id"]}))
        assert meta2["total_count"] == 2
        ids = {row["id"] for row in data2}
        assert ids == {wo_a1["id"], wo_a2["id"]}, (
            "client B's order must never appear under client A's filter"
        )
