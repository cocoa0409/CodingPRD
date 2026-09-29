"""Composite state builders and pytest fixtures.

Every precondition is built from scratch through the endpoints the PRD declares,
because each test starts against an empty database. The builders below are the
chains the workflows require: a composer with a signed agreement before a work
can be catalogued, a catalogued work plus a rate-card tier plus a licensee with
credit before a sync request can be quoted, an accepted request before a licence
can be issued, an active blanket agreement plus a registered cue sheet before a
usage report can be accepted, and so on.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pytest

from . import factories as build
from .api_client import MusicLibraryApiClient
from .api_errors import install_error_http_status_map
from .assertions import assert_created, assert_ok, assert_page
from .constants import CLOCK_ORIGIN
from .test_users import (
    ACCOUNTANT_ONE,
    CATALOG_ADMIN,
    LICENSING_AGENT,
    RIGHTS_MANAGER,
    make_composer_headers,
    make_licensee_headers,
)

JsonDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def read_composer(api: MusicLibraryApiClient, composer_id: str) -> JsonDict:
    return assert_ok(api.get_composer(composer_id, CATALOG_ADMIN))


def read_composition(api: MusicLibraryApiClient, composition_id: str) -> JsonDict:
    return assert_ok(api.get_composition(composition_id, CATALOG_ADMIN))


def read_licensee(api: MusicLibraryApiClient, licensee_id: str) -> JsonDict:
    return assert_ok(api.get_licensee(licensee_id, LICENSING_AGENT))


def read_license(api: MusicLibraryApiClient, license_id: str) -> JsonDict:
    return assert_ok(api.get_license(license_id, LICENSING_AGENT))


def read_agreement(api: MusicLibraryApiClient, agreement_id: str) -> JsonDict:
    return assert_ok(api.get_composer_agreement(agreement_id, RIGHTS_MANAGER))


def read_blanket_agreement(api: MusicLibraryApiClient, blanket_agreement_id: str) -> JsonDict:
    return assert_ok(api.get_blanket_agreement(blanket_agreement_id, LICENSING_AGENT))


def read_usage_report(api: MusicLibraryApiClient, usage_report_id: str) -> JsonDict:
    return assert_ok(api.get_usage_report(usage_report_id, LICENSING_AGENT))


def read_cue_sheet(api: MusicLibraryApiClient, cue_sheet_id: str) -> JsonDict:
    return assert_ok(api.get_cue_sheet(cue_sheet_id, RIGHTS_MANAGER))


def read_claim(api: MusicLibraryApiClient, claim_id: str) -> JsonDict:
    return assert_ok(api.get_infringement_claim(claim_id, RIGHTS_MANAGER))


def read_statement(api: MusicLibraryApiClient, statement_id: str) -> JsonDict:
    return assert_ok(api.get_royalty_statement(statement_id, ACCOUNTANT_ONE))


def composition_version(api: MusicLibraryApiClient, composition_id: str) -> int:
    """The composition `version` an issuance must echo back as its token."""
    return read_composition(api, composition_id)["version"]


def composer_version(api: MusicLibraryApiClient, composer_id: str) -> int:
    """The composer `version` a statement creation must echo back as its token."""
    return read_composer(api, composer_id)["version"]


def ledger_entries(
    api: MusicLibraryApiClient, composer_id: Optional[str] = None, **filters: Any
) -> List[JsonDict]:
    """Every ledger entry the accountant can see, optionally narrowed."""
    params: JsonDict = dict(filters)
    if composer_id is not None:
        params["composer_id"] = composer_id
    params.setdefault("limit", 100)
    rows, _meta = assert_page(api.list_royalty_ledger_entries(params, ACCOUNTANT_ONE))
    return rows


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


def advance_clock(api: MusicLibraryApiClient, to_iso8601: str) -> JsonDict:
    """Move the logical clock forward and return the sweep result."""
    return assert_ok(api.set_clock(to_iso8601, CATALOG_ADMIN))


# ---------------------------------------------------------------------------
# Composers and agreements
# ---------------------------------------------------------------------------


def new_composer(api: MusicLibraryApiClient, **overrides: Any) -> JsonDict:
    return assert_created(api.create_composer(build.composer_payload(**overrides), CATALOG_ADMIN))


def new_draft_agreement(
    api: MusicLibraryApiClient, composer_id: str, **overrides: Any
) -> JsonDict:
    payload = build.royalty_split_agreement_payload(composer_id, **overrides)
    return assert_created(api.create_composer_agreement(payload, RIGHTS_MANAGER))


def sign_agreement(
    api: MusicLibraryApiClient,
    agreement_id: str,
    composer_id: str,
    signature_name: str = "signature",
) -> JsonDict:
    """Submit a draft for signature and have the composer sign it."""
    assert_ok(api.submit_agreement_for_signature(agreement_id, None, RIGHTS_MANAGER))
    return assert_ok(
        api.sign_agreement(
            agreement_id,
            {"signature_name": signature_name},
            make_composer_headers(composer_id),
        )
    )


def new_active_agreement(
    api: MusicLibraryApiClient, composer_id: str, **overrides: Any
) -> JsonDict:
    """A ROYALTY_SPLIT agreement carried all the way to ACTIVE."""
    agreement = new_draft_agreement(api, composer_id, **overrides)
    return sign_agreement(api, agreement["id"], composer_id)


def new_active_work_for_hire_agreement(
    api: MusicLibraryApiClient, composer_id: str, **overrides: Any
) -> JsonDict:
    payload = build.work_for_hire_agreement_payload(composer_id, **overrides)
    agreement = assert_created(api.create_composer_agreement(payload, RIGHTS_MANAGER))
    return sign_agreement(api, agreement["id"], composer_id)


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------


@dataclass
class Work:
    """A composer, the agreement governing the work, and the work itself."""

    composer: JsonDict
    agreement: JsonDict
    composition: JsonDict

    @property
    def composer_id(self) -> str:
        return self.composer["id"]

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def composition_id(self) -> str:
        return self.composition["id"]

    @property
    def composer_headers(self) -> Dict[str, str]:
        return make_composer_headers(self.composer["id"])


def new_ingested_work(
    api: MusicLibraryApiClient,
    composer_overrides: Optional[JsonDict] = None,
    agreement_overrides: Optional[JsonDict] = None,
    **composition_overrides: Any,
) -> Work:
    """A work sitting at INGESTED under an ACTIVE agreement."""
    composer = new_composer(api, **(composer_overrides or {}))
    agreement = new_active_agreement(api, composer["id"], **(agreement_overrides or {}))
    composition = assert_created(
        api.create_composition(
            build.composition_payload(composer["id"], agreement["id"], **composition_overrides),
            CATALOG_ADMIN,
        )
    )
    return Work(composer, agreement, composition)


def catalog_work(api: MusicLibraryApiClient, work: Work) -> Work:
    """Take the work from INGESTED to CATALOGED, refreshing the stored row."""
    work.composition = assert_ok(
        api.catalog_composition(work.composition_id, None, CATALOG_ADMIN)
    )
    return work


def new_cataloged_work(
    api: MusicLibraryApiClient,
    composer_overrides: Optional[JsonDict] = None,
    agreement_overrides: Optional[JsonDict] = None,
    **composition_overrides: Any,
) -> Work:
    """A work eligible for search, sync requests and cue sheets."""
    work = new_ingested_work(
        api, composer_overrides, agreement_overrides, **composition_overrides
    )
    return catalog_work(api, work)


# ---------------------------------------------------------------------------
# Rate card, licensees and search profile
# ---------------------------------------------------------------------------


def new_tier(api: MusicLibraryApiClient, **overrides: Any) -> JsonDict:
    return assert_created(
        api.create_license_tier(build.license_tier_payload(**overrides), CATALOG_ADMIN)
    )


def new_blanket_tier(api: MusicLibraryApiClient, **overrides: Any) -> JsonDict:
    return assert_created(
        api.create_license_tier(build.blanket_tier_payload(**overrides), CATALOG_ADMIN)
    )


def new_licensee(api: MusicLibraryApiClient, **overrides: Any) -> JsonDict:
    return assert_created(
        api.create_licensee(build.licensee_payload(**overrides), LICENSING_AGENT)
    )


def put_default_search_profile(api: MusicLibraryApiClient, **overrides: Any) -> JsonDict:
    return assert_ok(
        api.put_search_profile(build.search_profile_payload(**overrides), CATALOG_ADMIN)
    )


# ---------------------------------------------------------------------------
# The sync-request conversation
# ---------------------------------------------------------------------------


@dataclass
class Deal:
    """A work, the rate card it is priced from, the buyer and the conversation."""

    work: Work
    tier: JsonDict
    licensee: JsonDict
    sync_request: Optional[JsonDict] = None
    license: Optional[JsonDict] = None

    @property
    def composition_id(self) -> str:
        return self.work.composition_id

    @property
    def tier_id(self) -> str:
        return self.tier["id"]

    @property
    def licensee_id(self) -> str:
        return self.licensee["id"]

    @property
    def sync_request_id(self) -> str:
        assert self.sync_request is not None
        return self.sync_request["id"]

    @property
    def license_id(self) -> str:
        assert self.license is not None
        return self.license["id"]

    @property
    def licensee_headers(self) -> Dict[str, str]:
        return make_licensee_headers(self.licensee["id"])

    @property
    def composer_headers(self) -> Dict[str, str]:
        return self.work.composer_headers


def new_deal_ground(
    api: MusicLibraryApiClient,
    work_overrides: Optional[JsonDict] = None,
    tier_overrides: Optional[JsonDict] = None,
    licensee_overrides: Optional[JsonDict] = None,
) -> Deal:
    """A catalogued work, a per-use tier and a licensee with credit."""
    work = new_cataloged_work(api, **(work_overrides or {}))
    tier = new_tier(api, **(tier_overrides or {}))
    licensee = new_licensee(api, **(licensee_overrides or {}))
    return Deal(work, tier, licensee)


def submit_sync_request(api: MusicLibraryApiClient, deal: Deal, **overrides: Any) -> Deal:
    """Raise the request, leaving it in SUBMITTED."""
    payload = build.sync_request_payload(
        deal.composition_id, deal.licensee_id, deal.tier_id, **overrides
    )
    deal.sync_request = assert_created(api.create_sync_request(payload, LICENSING_AGENT))
    return deal


def review_sync_request(api: MusicLibraryApiClient, deal: Deal) -> Deal:
    deal.sync_request = assert_ok(
        api.review_sync_request(deal.sync_request_id, None, LICENSING_AGENT)
    )
    return deal


def quote_sync_request(
    api: MusicLibraryApiClient, deal: Deal, quote_valid_days: Optional[int] = None
) -> Deal:
    payload = None if quote_valid_days is None else build.quote_payload(quote_valid_days)
    deal.sync_request = assert_ok(
        api.quote_sync_request(deal.sync_request_id, payload, LICENSING_AGENT)
    )
    return deal


def accept_sync_request(api: MusicLibraryApiClient, deal: Deal) -> Deal:
    deal.sync_request = assert_ok(
        api.accept_sync_request(deal.sync_request_id, None, deal.licensee_headers)
    )
    return deal


def new_quoted_deal(
    api: MusicLibraryApiClient,
    work_overrides: Optional[JsonDict] = None,
    tier_overrides: Optional[JsonDict] = None,
    licensee_overrides: Optional[JsonDict] = None,
    quote_valid_days: Optional[int] = None,
    **request_overrides: Any,
) -> Deal:
    """Ground plus a request carried SUBMITTED -> UNDER_REVIEW -> QUOTED."""
    deal = new_deal_ground(api, work_overrides, tier_overrides, licensee_overrides)
    submit_sync_request(api, deal, **request_overrides)
    review_sync_request(api, deal)
    return quote_sync_request(api, deal, quote_valid_days)


def new_accepted_deal(
    api: MusicLibraryApiClient,
    work_overrides: Optional[JsonDict] = None,
    tier_overrides: Optional[JsonDict] = None,
    licensee_overrides: Optional[JsonDict] = None,
    quote_valid_days: Optional[int] = None,
    **request_overrides: Any,
) -> Deal:
    """A quoted request the owning licensee has accepted."""
    deal = new_quoted_deal(
        api,
        work_overrides,
        tier_overrides,
        licensee_overrides,
        quote_valid_days,
        **request_overrides,
    )
    return accept_sync_request(api, deal)


# ---------------------------------------------------------------------------
# Licences
# ---------------------------------------------------------------------------


def issue_per_use_license(api: MusicLibraryApiClient, deal: Deal, **overrides: Any) -> Deal:
    """Issue from the accepted request, echoing the work's current version."""
    payload = build.per_use_license_payload(
        deal.sync_request_id, composition_version(api, deal.composition_id), **overrides
    )
    deal.license = assert_created(api.create_license(payload, LICENSING_AGENT))
    return deal


def new_issued_deal(
    api: MusicLibraryApiClient,
    work_overrides: Optional[JsonDict] = None,
    tier_overrides: Optional[JsonDict] = None,
    licensee_overrides: Optional[JsonDict] = None,
    **request_overrides: Any,
) -> Deal:
    """An accepted request that has produced a licence in ISSUED."""
    deal = new_accepted_deal(
        api, work_overrides, tier_overrides, licensee_overrides, None, **request_overrides
    )
    return issue_per_use_license(api, deal)


def activate_license(api: MusicLibraryApiClient, deal: Deal) -> Deal:
    deal.license = assert_ok(api.activate_license(deal.license_id, None, LICENSING_AGENT))
    return deal


def pay_license_in_full(api: MusicLibraryApiClient, deal: Deal) -> Deal:
    """Collect the whole fee, which stamps the sync-fee entry's cash instant."""
    assert deal.license is not None
    deal.license = assert_ok(
        api.record_license_payment(
            deal.license_id,
            {"amount_cents": deal.license["final_fee_cents"]},
            ACCOUNTANT_ONE,
        )
    )
    return deal


# ---------------------------------------------------------------------------
# Blanket coverage, usage reports and cue sheets
# ---------------------------------------------------------------------------


@dataclass
class Blanket:
    """A licensee, the blanket agreement covering it and a blanket-eligible tier."""

    licensee: JsonDict
    agreement: JsonDict
    tier: Optional[JsonDict] = None
    usage_report: Optional[JsonDict] = None

    @property
    def licensee_id(self) -> str:
        return self.licensee["id"]

    @property
    def agreement_id(self) -> str:
        return self.agreement["id"]

    @property
    def usage_report_id(self) -> str:
        assert self.usage_report is not None
        return self.usage_report["id"]

    @property
    def licensee_headers(self) -> Dict[str, str]:
        return make_licensee_headers(self.licensee["id"])


def new_draft_blanket(
    api: MusicLibraryApiClient,
    licensee: Optional[JsonDict] = None,
    with_tier: bool = False,
    **overrides: Any,
) -> Blanket:
    """A blanket agreement in DRAFT coverage and COMPLIANT reporting."""
    licensee = licensee or new_licensee(api)
    agreement = assert_created(
        api.create_blanket_agreement(
            build.blanket_agreement_payload(licensee["id"], **overrides), LICENSING_AGENT
        )
    )
    tier = new_blanket_tier(api) if with_tier else None
    return Blanket(licensee, agreement, tier)


def new_active_blanket(
    api: MusicLibraryApiClient,
    licensee: Optional[JsonDict] = None,
    with_tier: bool = False,
    **overrides: Any,
) -> Blanket:
    """A blanket agreement whose coverage axis reads ACTIVE."""
    blanket = new_draft_blanket(api, licensee, with_tier, **overrides)
    blanket.agreement = assert_ok(
        api.activate_blanket_agreement(blanket.agreement_id, None, LICENSING_AGENT)
    )
    return blanket


def open_usage_report(api: MusicLibraryApiClient, blanket: Blanket, **overrides: Any) -> Blanket:
    """Open the cadence period's report, landing in DUE."""
    blanket.usage_report = assert_created(
        api.create_usage_report(
            build.usage_report_payload(blanket.agreement_id, **overrides), LICENSING_AGENT
        )
    )
    return blanket


def new_cue_sheet(
    api: MusicLibraryApiClient,
    cues: List[JsonDict],
    license_id: Optional[str] = None,
    usage_report_id: Optional[str] = None,
    **overrides: Any,
) -> JsonDict:
    """A cue sheet in COLLECTED with its credits already computed."""
    payload = build.cue_sheet_payload(
        cues, license_id=license_id, usage_report_id=usage_report_id, **overrides
    )
    return assert_created(api.create_cue_sheet(payload, LICENSING_AGENT))


def register_cue_sheet(
    api: MusicLibraryApiClient, cue_sheet_id: str, society_reference: str = "SOC-REF-1"
) -> JsonDict:
    """File the sheet with a society, which recognizes the performance money."""
    return assert_ok(
        api.register_cue_sheet(
            cue_sheet_id, {"society_reference": society_reference}, RIGHTS_MANAGER
        )
    )


def new_registered_cue_sheet(
    api: MusicLibraryApiClient,
    cues: List[JsonDict],
    license_id: Optional[str] = None,
    usage_report_id: Optional[str] = None,
    society_reference: str = "SOC-REF-1",
    **overrides: Any,
) -> JsonDict:
    sheet = new_cue_sheet(
        api, cues, license_id=license_id, usage_report_id=usage_report_id, **overrides
    )
    return register_cue_sheet(api, sheet["id"], society_reference)


def submit_usage_report(api: MusicLibraryApiClient, blanket: Blanket) -> Blanket:
    """Only the owning licensee may submit, and only with a sheet attached."""
    blanket.usage_report = assert_ok(
        api.submit_usage_report(blanket.usage_report_id, None, blanket.licensee_headers)
    )
    return blanket


def accept_usage_report(api: MusicLibraryApiClient, blanket: Blanket) -> Blanket:
    """Acceptance runs the five-step pool cascade."""
    blanket.usage_report = assert_ok(
        api.accept_usage_report(blanket.usage_report_id, None, RIGHTS_MANAGER)
    )
    return blanket


def new_submitted_report_with_sheet(
    api: MusicLibraryApiClient,
    work: Optional[Work] = None,
    blanket: Optional[Blanket] = None,
    cues: Optional[List[JsonDict]] = None,
    **blanket_overrides: Any,
) -> Tuple[Blanket, Work, JsonDict]:
    """An ACTIVE agreement, a DUE report carrying one REGISTERED sheet, submitted."""
    work = work or new_cataloged_work(api)
    blanket = blanket or new_active_blanket(api, **blanket_overrides)
    open_usage_report(api, blanket)
    sheet = new_registered_cue_sheet(
        api,
        cues if cues is not None else [build.cue(work.composition_id, "THEME", 45)],
        usage_report_id=blanket.usage_report_id,
    )
    submit_usage_report(api, blanket)
    return blanket, work, sheet


# ---------------------------------------------------------------------------
# Detections, claims and settlement
# ---------------------------------------------------------------------------


def new_fingerprint_match(
    api: MusicLibraryApiClient, composition_id: str, **overrides: Any
) -> JsonDict:
    return assert_created(
        api.create_fingerprint_match(
            build.fingerprint_match_payload(composition_id, **overrides), CATALOG_ADMIN
        )
    )


def new_detected_claim(
    api: MusicLibraryApiClient, composition_id: str, **match_overrides: Any
) -> Tuple[JsonDict, JsonDict]:
    """A detection and the claim built from it, sitting in DETECTED."""
    match = new_fingerprint_match(api, composition_id, **match_overrides)
    claim = assert_created(
        api.create_infringement_claim({"fingerprint_match_id": match["id"]}, RIGHTS_MANAGER)
    )
    return match, claim


def notice_claim(
    api: MusicLibraryApiClient, claim_id: str, notice_channel: str = "PLATFORM"
) -> JsonDict:
    """Serve the takedown, which restricts an AVAILABLE work."""
    return assert_ok(
        api.notice_claim(claim_id, {"notice_channel": notice_channel}, RIGHTS_MANAGER)
    )


def new_noticed_claim(
    api: MusicLibraryApiClient, composition_id: str, **match_overrides: Any
) -> Tuple[JsonDict, JsonDict]:
    match, claim = new_detected_claim(api, composition_id, **match_overrides)
    return match, notice_claim(api, claim["id"])


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


def new_draft_statement(api: MusicLibraryApiClient, composer_id: str, **overrides: Any) -> JsonDict:
    """Sweep the composer's ledger into a DRAFT statement with a fresh token."""
    payload = build.statement_payload(
        composer_id, composer_version(api, composer_id), **overrides
    )
    return assert_created(api.create_royalty_statement(payload, ACCOUNTANT_ONE))


def finalize_statement(api: MusicLibraryApiClient, statement_id: str) -> JsonDict:
    return assert_ok(api.finalize_royalty_statement(statement_id, None, ACCOUNTANT_ONE))


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api() -> MusicLibraryApiClient:
    """A client for a freshly launched service whose clock sits at its origin."""
    install_error_http_status_map()
    return MusicLibraryApiClient()


@pytest.fixture
def clock_origin() -> str:
    """The instant the logical clock starts at before any advance."""
    return CLOCK_ORIGIN


@pytest.fixture
def composer(api: MusicLibraryApiClient) -> JsonDict:
    return new_composer(api)


@pytest.fixture
def ingested_work(api: MusicLibraryApiClient) -> Work:
    return new_ingested_work(api)


@pytest.fixture
def cataloged_work(api: MusicLibraryApiClient) -> Work:
    return new_cataloged_work(api)


@pytest.fixture
def tier(api: MusicLibraryApiClient) -> JsonDict:
    return new_tier(api)


@pytest.fixture
def licensee(api: MusicLibraryApiClient) -> JsonDict:
    return new_licensee(api)


@pytest.fixture
def search_profile(api: MusicLibraryApiClient) -> JsonDict:
    return put_default_search_profile(api)


@pytest.fixture
def deal_ground(api: MusicLibraryApiClient) -> Deal:
    return new_deal_ground(api)


@pytest.fixture
def quoted_deal(api: MusicLibraryApiClient) -> Deal:
    return new_quoted_deal(api)


@pytest.fixture
def accepted_deal(api: MusicLibraryApiClient) -> Deal:
    return new_accepted_deal(api)


@pytest.fixture
def issued_deal(api: MusicLibraryApiClient) -> Deal:
    return new_issued_deal(api)


@pytest.fixture
def draft_blanket(api: MusicLibraryApiClient) -> Blanket:
    return new_draft_blanket(api)


@pytest.fixture
def active_blanket(api: MusicLibraryApiClient) -> Blanket:
    return new_active_blanket(api)
