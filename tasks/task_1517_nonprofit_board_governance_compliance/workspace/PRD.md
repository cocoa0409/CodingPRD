# Nonprofit Board Governance & Compliance API — Product Requirements Document

## 1. Introduction

A 501(c)(3) board of directors operates under a web of overlapping obligations: its own bylaws dictate quorum and term limits, state charity regulators demand timely registration renewals in every solicitation jurisdiction, the IRS expects an annual Form 990 reviewed by the board and disclosed to the public, insurers must be bound without coverage gaps, and every director owes an annual conflict-of-interest disclosure whose review is segregated from the filer. Today most organizations track these duties in spreadsheets and inboxes, and a single missed lapse — an expired charitable registration, an unreviewed filing, a termed-out director silently re-elected — can jeopardize the organization's tax-exempt standing.

This document specifies the Nonprofit Board Governance & Compliance API, a system of record for the full governance calendar of a tax-exempt organization. It manages the founding and amendment of bylaws, the election of directors into version-pinned terms, the chartering and staffing of committees, the scheduling and quorum verification of board and committee meetings, the introduction and disposition of motions with per-category voting thresholds, the filing and peer review of conflict-of-interest disclosures, the annual evaluation of the executive director, succession planning for key offices, the preparation and board review of Form 990 filings, multi-jurisdiction charitable registration renewals with tiered fee schedules, and directors-and-officers insurance oversight. Every obligation feeds a single derived compliance posture for the organization, and that posture in turn gates what the board may lawfully do — most visibly, a non-compliant organization may not introduce fundraising motions. All date-driven behavior is evaluated against a controllable logical clock, and an explicit compliance sweep applies every time-based transition as of that clock.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Access to each operation is restricted to a designated list of roles; a caller whose role is not on the endpoint's list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `GovernanceAdmin`, `BoardChair`, `BoardDirector`, `Treasurer`, `ComplianceOfficer`, and `ExecutiveDirector`.

Three roles are entity-backed by the board roster. When `X-User-Role` is `BoardChair`, `X-User-ID` must be the `id` of an `ACTIVE` `BoardMember` whose `officer_role` is `CHAIR`; when `X-User-Role` is `Treasurer`, `X-User-ID` must be the `id` of an `ACTIVE` `BoardMember` whose `officer_role` is `TREASURER`; when `X-User-Role` is `BoardDirector`, `X-User-ID` must be the `id` of any `ACTIVE` `BoardMember`. In all three cases the member must belong to the nonprofit being acted on, and ownership checks on any resource that references a `BoardMember` compare the resource's foreign-key field to `X-User-ID`. A caller who fails this qualification is rejected with `ERR_IDENTITY_NOT_QUALIFIED` (HTTP 403). The remaining three roles carry opaque identifiers: when `X-User-Role` is `GovernanceAdmin`, `ComplianceOfficer`, or `ExecutiveDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `preparer_user_id` on a filing, `minutes_recorded_by` on a meeting, or `recorded_by_user_id` on an evaluation — but it does not compare such identifiers to any entity's `id`.

Two operations are strictly self-service: casting a vote and filing a conflict-of-interest disclosure both require the payload's `board_member_id` to equal the caller's `X-User-ID` — a director votes and discloses only as themself, and a mismatch is rejected with `ERR_FORBIDDEN_FOR_ROLE`. Resignation is partially self-service: a `GovernanceAdmin` or `BoardChair` may record any director's resignation, while a `BoardDirector`, `BoardChair`, or `Treasurer` acting in their entity-backed capacity may resign only for themself, meaning `X-User-ID` must equal the member's `id`. The `ExecutiveDirector` role is a read-only observer, deliberately excluded from every evaluation and governance write as a matter of segregation from their own evaluation.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination and List Filtering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

List endpoints additionally accept resource-specific filter parameters, all matched exactly: bylaws by `nonprofit_id` and `status`; bylaws amendments by `nonprofit_id`, `base_bylaws_id`, `status`, and `motion_id`; board members by `nonprofit_id`, `status`, and `skill` (a single skill tag from the recruitment matrix vocabulary); board terms by `nonprofit_id`, `board_member_id`, `status`, and `bylaws_id`; committees by `nonprofit_id`, `status`, and `type`; committee appointments by `nonprofit_id`, `committee_id`, `board_member_id`, and `status`; meetings by `nonprofit_id`, `committee_id`, and `status`; motions by `nonprofit_id`, `meeting_id`, `category`, `status`, and `bylaws_amendment_id`; votes by `nonprofit_id`, `motion_id`, and `board_member_id`; disclosures by `nonprofit_id`, `board_member_id`, `fiscal_year`, `status`, and `reviewer_member_id`; evaluations by `nonprofit_id`, `fiscal_year`, and `status`; succession plans by `nonprofit_id`, `target_role`, `status`, and `interim_designee_member_id`; Form 990 filings by `nonprofit_id`, `fiscal_year`, `status`, and `supersedes_filing_id`; state registrations by `nonprofit_id`, `state_code`, and `status`; and insurance policies by `nonprofit_id`, `policy_type`, `status`, and `prior_policy_id`.

### 2.4. The Logical Clock and the Compliance Sweep

Every date rule in the system — fiscal year derivation, filing deadlines, renewal windows, coverage expiry, disclosure delinquency — reads a server-held **logical clock**, never the wall clock. At startup, before any client call, the logical clock is exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. An admin-only test-driving capability, available to `GovernanceAdmin`, sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Setting the clock fires no entity transitions by itself; time-based transitions are applied only by an explicit ops-run checkpoint, the **compliance sweep**, which a `GovernanceAdmin` or `ComplianceOfficer` invokes against a single nonprofit.

One sweep applies, as of the current logical clock: scheduled board terms whose window has opened become `ACTIVE` and active terms past their end become `COMPLETED`; members whose latest term completed transition to `PAST` or `TERM_LIMITED_OUT` as the term-limit rules dictate; registrations move to `RENEWAL_DUE` inside their sixty-day window or to `LAPSED` at period expiry, with the fundraising-motion withdrawal cascade that lapse triggers; insurance policies past their end date expire; Form 990 filings have their public-disclosure overdue flag recomputed; and the nonprofit's `compliance_posture` is recomputed. Sweep transitions are system-initiated and require no client request on the affected resources.

### 2.5. Common Resource Properties

All primary resources — nonprofits, bylaws, bylaws amendments, board members, board terms, committees, committee appointments, meetings, motions, conflict-of-interest disclosures, executive evaluations, succession plans, Form 990 filings, state registrations, and insurance policies — share a standard set of system-managed fields:

- **`id` (string):** a server-minted UUID with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer that increments by exactly 1 with every mutation, including mutations caused by cascade side effects rather than direct client writes.

The one exception is the `Vote` record, which is append-only and immutable once recorded: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent.

### 2.6. Optimistic Concurrency Control

Exactly three write endpoints are guarded by optimistic concurrency control, and each names its guard field after the parent entity it modifies:

- `POST /boardgov/meetings/{id}/minutes` requires `expected_meeting_version`, carrying the client's last observed `version` of the meeting. If another writer has advanced the meeting's version since the client last read it — for example, because a colleague legitimately recorded a replacement draft — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a minutes writer from overwriting a draft it has not observed.
- `PATCH /boardgov/executive-evaluations/{id}/scores` requires `expected_evaluation_version`, carrying the client's last observed `version` of the evaluation. A mismatch with the evaluation's current `version` — which advances on every legitimate score-sheet edit — is rejected with `ERR_STALE_VERSION` (HTTP 412), so a writer never edits against a stale baseline.
- `PATCH /boardgov/nonprofits/{id}` requires `expected_nonprofit_version`, carrying the client's last observed `version` of the nonprofit. Because profile fields such as `annual_gross_receipts_cents` feed registration fee estimates and the insurance coverage floor, a stale write is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than allowed to overwrite profile changes it could not have seen.

On all three endpoints the expected-version field is non-optional. Endpoints not listed here do not take a version field at all.

### 2.7. Validation Order of Precedence

When a request fails several rules at once, the error the caller receives is determined by a fixed order of precedence, evaluated from first to last:

1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization.** The caller's role must appear in the endpoint's roles list, else `ERR_FORBIDDEN_FOR_ROLE` (403).
3. **Entity-backed role qualification.** Callers acting as `BoardChair`, `BoardDirector`, or `Treasurer` must satisfy the roster qualification of §2.1 — an `ACTIVE` `BoardMember` of the nonprofit being acted on, with the matching `officer_role` for officer roles — else `ERR_IDENTITY_NOT_QUALIFIED` (403).
4. **Self-service ownership.** Vote casts and disclosure filings require payload `board_member_id` equal to `X-User-ID`, else `ERR_FORBIDDEN_FOR_ROLE` (403).

Malformed requests short-circuit immediately after this auth block and before any existence or state check: a missing required field, a wrong-typed value, an enum value outside its defined set, a negative amount, an empty `proposed_fields` or `answers` or `restriction_categories` payload, or an end boundary not after its start boundary is rejected with `ERR_INVALID_REQUEST` (400).

5. **Path existence.** Path resource identifiers are validated left to right; the first identifier that does not resolve rejects the request with `ERR_NOT_FOUND` (404).
6. **Body reference integrity.** Body-referenced identifiers — `base_bylaws_id`, `board_member_id`, `committee_id`, `meeting_id`, `motion_id`, `bylaws_amendment_id`, `prior_policy_id`, `supersedes_filing_id`, and `interim_designee_member_id` — must exist and belong to the same nonprofit, else `ERR_REFERENCED_NOT_FOUND` (422).
7. **State-machine from-state.** The target resource must be in a state from which the requested transition is allowed, else `ERR_INVALID_STATE` (409); this also covers transitions attempted on terminal resources and non-idempotent re-fires.
8. **Optimistic concurrency.** On the three guarded endpoints of §2.6, the expected version must equal the parent's current `version`, else `ERR_STALE_VERSION` (412).
9. **Cross-entity state gates.** Business referential gates such as an adopted-bylaws requirement, an in-session meeting requirement, or amendment linkage rules — `ERR_BYLAWS_NOT_ADOPTED`, `ERR_MEETING_NOT_IN_SESSION`, `ERR_MOTION_NOT_OPEN`, `ERR_COMMITTEE_NOT_ACTIVE`, `ERR_AMENDMENT_NOT_PROPOSED`, `ERR_AMENDMENT_HAS_OPEN_MOTION`, `ERR_VOTER_NOT_ELIGIBLE` — each a 409 detailed in §3.
10. **Segregation of duties.** Same-user prohibitions — `ERR_SEGREGATION_OF_DUTIES`, `ERR_REVIEWER_MISMATCH`, `ERR_EVALUATION_RECORDER_MISMATCH` — each a 409 detailed in §3.
11. **Recusal.** A recused member attempting a non-recused vote is rejected with `ERR_MEMBER_RECUSED` (409).
12. **Compliance posture gate.** Fundraising motions introduced while the organization is non-compliant are rejected with `ERR_NONCOMPLIANT_POSTURE_BLOCKS` (409).
13. **Reviewer qualification.** `ERR_REVIEWER_NOT_QUALIFIED` and `ERR_REVIEWER_NOT_COMPLIANT` (409).
14. **Uniqueness.** All duplicate-resource rules — `ERR_DUPLICATE_EIN`, `ERR_DUPLICATE_MEMBER_EMAIL`, `ERR_DUPLICATE_DISCLOSURE`, `ERR_DUPLICATE_FILING`, `ERR_DUPLICATE_EVALUATION`, `ERR_DUPLICATE_REGISTRATION`, `ERR_DUPLICATE_COMMITTEE_NAME`, `ERR_DUPLICATE_COMMITTEE_CHAIR`, `ERR_DUPLICATE_APPOINTMENT`, `ERR_DUPLICATE_VOTE`, `ERR_DUPLICATE_REVIEW` — each a 409.
15. **Election eligibility.** Member status, term-limit chain, and seat availability, evaluated in that internal order: `ERR_MEMBER_NOT_ELIGIBLE`, then `ERR_TERM_LIMIT_EXCEEDED`, then `ERR_NO_SEATS_AVAILABLE` (409).
16. **Committee appointment gates.** `ERR_COMMITTEE_FULL`, `ERR_COMMITTEE_NOT_INDEPENDENT`, `ERR_COI_REVIEW_REQUIRED` alongside the eligibility error above (409).
17. **Committee activation gates.** `ERR_COMMITTEE_BELOW_MIN` with the independence and review errors (409).
18. **Interval rules.** `ERR_TERM_OVERLAP`, `ERR_MEETING_OVERLAP`, `ERR_COVERAGE_GAP`, `ERR_POLICY_OVERLAP` (409).
19. **Window and deadline rules.** `ERR_MEETING_TOO_EARLY`, `ERR_NOTICE_INSUFFICIENT`, `ERR_RENEWAL_TOO_EARLY`, `ERR_POLICY_NOT_YET_EFFECTIVE` (409).
20. **Money checks come last** among business rules: `ERR_RENEWAL_FEE_MISMATCH` and `ERR_COVERAGE_BELOW_FLOOR` (409).
21. **Aggregate participation thresholds** at action time: `ERR_QUORUM_NOT_MET` and `ERR_REVIEW_COVERAGE_INSUFFICIENT` (409).
22. **Domain-shape rules.** `ERR_EVALUATION_INCOMPLETE`, `ERR_DESIGNEE_REQUIRED`, `ERR_MINUTES_APPROVAL_MEETING_INVALID` (409).

### 2.8. Interval Semantics: Terms, Meetings, and Policies

Three distinct interval semantics coexist in the system, and conflating them is the single most common integration error.

**Board terms use half-open adjacency.** A term occupies the interval from its `start_date` up to but not including its `end_date`. A newly elected term may begin on the exact day the member's previous term ends — strict adjacency continues a consecutive-service chain and is always allowed — while any true overlap with the member's existing non-`VACATED` terms is rejected with `ERR_TERM_OVERLAP`. Within chain arithmetic, any positive gap between one term's end and the next term's start breaks the chain.

**Meetings require a thirty-minute buffer.** The contended resource is the meeting's scope, the pairing of `nonprofit_id` and `committee_id`: board meetings contend only with board meetings of the same organization, and committee meetings contend only with meetings of the same committee. A new meeting conflicts with an existing non-`CANCELLED` meeting of the same scope whenever the new meeting's start falls before the existing meeting's end plus thirty minutes and the existing meeting's start falls before the new meeting's end plus thirty minutes, where a meeting's end is its `scheduled_start` plus its `duration_minutes`. The buffer applies on both sides, so a new meeting starting at the exact instant another ends is still a conflict; exactly thirty minutes of separation passes, while twenty-nine minutes fails. Conflicts are rejected with `ERR_MEETING_OVERLAP`.

**Insurance renewals must abut.** A renewal linked by `prior_policy_id` is measured in whole days from the prior policy's `policy_end_date` to the new policy's `policy_start_date`, recorded as `gap_days`. A negative gap means the new policy starts before the prior ended, an overlap rejected with `ERR_POLICY_OVERLAP`; a zero gap is continuous coverage; a positive gap is a coverage lapse that must be explicitly acknowledged via `acknowledge_gap`, else `ERR_COVERAGE_GAP`. Independently of the renewal chain, a policy's half-open coverage interval must not overlap any other non-terminal policy — one in `QUOTED`, `BOUND`, or `ACTIVE` — of the same organization and the same `policy_type`: two intervals overlap when the new policy's start falls before the other's end and the other's start falls before the new policy's end, so abutting intervals are allowed.

### 2.9. Monetary Precision and Rounding Conventions

All monetary values are integers denominated in cents — fields such as `annual_gross_receipts_cents`, `coverage_limit_cents`, `premium_cents`, `paid_fee_cents`, `renewal_fee_cents`, `total_revenue_cents`, `total_expenses_cents`, `contributions_cents`, `program_service_revenue_cents`, `contributions_in_state_cents`, and `net_change_cents` — and money arithmetic is performed in whole cents. The registration renewal fee has a pinned rounding order that must not be rearranged: the tier-4 overage surcharge is ceiled to a whole increment first, then the ten percent late fee — when it applies — is computed on the sum of base and surcharge and rounded half-up to whole cents, and only then are the components summed; computing the late fee on raw unrounded components would produce different cents. Composite evaluation scores are carried at exactly 2 decimal places using round-half-up. The public support ratio on a Form 990 filing is carried at exactly 4 decimal places using round-half-up. Quorum and review-coverage arithmetic yields whole seats or whole members, with exact halves always rounding up (ceiling). Date arithmetic is performed in whole days, and a span of "N years" means the same calendar date N years later.

### 2.10. Cascade Chains and Cross-Entity Consistency

The server maintains consistency across aggregates automatically: when one transition's side effects render another entity's state untenable, the dependent transition fires as part of the same operation, without any client request on the affected resource, and every resource mutated along the way has its `updated_at` refreshed and its `version` incremented per §2.5. The named chains, each detailed where it arises in §3, are:

- **Departure chain (resignation or removal).** The member's scheduled or active term is vacated (link 1a); the member's active committee appointments end with the corresponding reason (link 1b); each affected committee recomputes its active membership and an `ACTIVE` committee that falls below its minimum goes `DORMANT` (link 2); and a committee going dormant has its scheduled meetings cancelled (link 3). The freed seat returns to the organization's open-seat pool.
- **Conflict-of-interest restriction chain.** Imposing restrictions flags the member, ends the member's appointments on committees whose type maps to a restricted category, and propagates the same dormant-and-cancellation wave as the departure chain.
- **Bylaws adoption chain.** A passed bylaws motion adopts the amendment, mints a successor bylaws document that supersedes its base, and re-points all future governance inputs to the new document.
- **Registration lapse chain.** A lapsed registration drives the organization's posture to `NON_COMPLIANT`, and that posture change withdraws every in-flight fundraising motion.
- **Supersede chains.** Marking an amendment filing as filed supersedes its target filing; approving a succession plan supersedes the previously approved plan for the same role.

## 3. Business Logic & Workflows

### 3.1. Incorporation, Founding Bylaws, and Amendments

A `GovernanceAdmin` incorporates an organization by providing its legal `name`, its `ein` (the Employer Identification Number, which must be globally unique across all nonprofits — a collision is rejected with `ERR_DUPLICATE_EIN`), the two-letter `state_of_incorporation`, the `fiscal_year_end_month` as an integer from 1 to 12, and the most recently reported `annual_gross_receipts_cents`. Two fields are derived rather than supplied. The `current_fiscal_year` is the calendar year of the fiscal-year end that contains the logical clock date, where a fiscal year runs from the first day of the month following the end month through the last day of the end month of the label year — so a December year-end yields fiscal years aligned to calendar years, while a June year-end labels the year by the calendar year in which it closes. The `compliance_posture` — one of `COMPLIANT`, `AT_RISK`, or `NON_COMPLIANT` — is derived from registrations, filings, coverage, and disclosure delinquency per §3.9, and a freshly incorporated organization starts at `NON_COMPLIANT` because no directors-and-officers coverage exists yet. The organization also carries an `adopted_policies` register that the policy-motion workflow appends to. Profile maintenance is a guarded write per §2.6: the request must carry `expected_nonprofit_version`, may update `name`, `state_of_incorporation`, `fiscal_year_end_month`, or `annual_gross_receipts_cents`, increments the nonprofit's `version` by 1, and recomputes the posture whenever the receipts figure changes, since both the fee estimate and the coverage floor read the new value.

Every organization's governance is anchored in a **bylaws document**. A `GovernanceAdmin` drafts the founding bylaws with `quorum_pct` (an integer between 1 and 100 inclusive), a `quorum_basis` of either `SEATED` or `AUTHORIZED`, an `amendment_threshold_pct` (an integer between 51 and 100 inclusive), a `term_length_years` between 1 and 6 inclusive, a `max_consecutive_terms` of at least 1, a `term_cooloff_years` of at least 0, and a `board_size` of at least 3 authorized seats. A new document is `DRAFT` with `version_no` 1 and a null `adopted_at`. Founding adoption — the incorporator's act, performed by a `GovernanceAdmin` — moves a `DRAFT` document to `ADOPTED` and stamps `adopted_at` from the logical clock; it is refused with `ERR_BYLAWS_ALREADY_ADOPTED` when another bylaws document is already `ADOPTED` for the same nonprofit, and attempting it on a non-draft document is rejected with `ERR_INVALID_STATE`. A `DRAFT` document may instead be discarded to `DISCARDED`. Both `SUPERSEDED` and `DISCARDED` are terminal.

Later change flows only through amendments; the founding-adoption path is not available once any document is adopted. A `BoardChair`, a `BoardDirector`, or a `GovernanceAdmin` may draft an amendment against an `ADOPTED` base document, supplying `nonprofit_id`, the `base_bylaws_id` of that base, a short `title`, and a `proposed_fields` object carrying a non-empty subset of the seven bylaws knobs (`quorum_pct`, `quorum_basis`, `amendment_threshold_pct`, `term_length_years`, `max_consecutive_terms`, `term_cooloff_years`, `board_size`). An empty subset is rejected with `ERR_INVALID_REQUEST`, and a base that is not `ADOPTED` is rejected with `ERR_BYLAWS_NOT_ADOPTED`. The amendment is born `DRAFT` with a null `motion_id` until a bylaws-category motion claims it. A `BoardChair` then puts a `DRAFT` amendment before the board, moving it to `PROPOSED` — the same base-adopted and non-empty-fields gates apply. Withdrawal behaves differently by state: a `DRAFT` amendment may be withdrawn freely, while withdrawing a `PROPOSED` amendment is refused with `ERR_AMENDMENT_HAS_OPEN_MOTION` if any non-terminal motion — one still `INTRODUCED`, `VOTING_OPEN`, or `TABLED` — references it. A defeated amendment's `motion_id` is cleared so the board may rework the text, and the `BoardChair` may return a `DEFEATED` amendment to `DRAFT` for revision, which is the cycle that lets a single amendment be voted more than once. The adoption cascade itself — successor minting, supersession, and the re-pointing of future elections — is described with the voting machinery in §3.5.

### 3.2. Directors, Terms, and the Recruitment Matrix

A director enters the system as a nominee: a `GovernanceAdmin` proposes a board member with `full_name`, an `email` that must be unique within the nonprofit (`ERR_DUPLICATE_MEMBER_EMAIL`), a `skill_tags` list drawn from the recruitment vocabulary of `FINANCE`, `LEGAL`, `FUNDRAISING`, `PROGRAM`, `GOVERNANCE`, `MARKETING`, `TECHNOLOGY`, and `HR`, an `officer_role` of `NONE`, `CHAIR`, `TREASURER`, or `SECRETARY` defaulting to `NONE`, and an `is_independent` flag defaulting to true. The `officer_role` is what qualifies the entity-backed identities of §2.1, and `is_independent` gates audit-committee service. A nominee is `PROPOSED`; the full member lifecycle runs `PROPOSED` to `ACTIVE` to either `PAST` or `TERM_LIMITED_OUT`, with `RESIGNED` and `REMOVED` as terminal departures and re-election allowed from `PAST` or `TERM_LIMITED_OUT` back to `ACTIVE`. Profile maintenance — revising `full_name`, `skill_tags`, `officer_role`, or `is_independent` — is a `GovernanceAdmin` write that increments the member's `version` by 1.

Election seats a member: a `BoardChair` or `GovernanceAdmin` creates a board term carrying `nonprofit_id`, `board_member_id`, and `start_date`. Three eligibility gates apply, evaluated in a fixed internal order — member status first, then the term-limit chain, then seat availability. The member must be `PROPOSED`, `PAST`, `TERM_LIMITED_OUT`, or `ACTIVE` — an `ACTIVE` incumbent may be re-elected to a non-overlapping next term — while `RESIGNED` or `REMOVED` members are rejected with `ERR_MEMBER_NOT_ELIGIBLE`. Next, the term-limit chain is measured: all of the member's terms (scheduled, active, completed, and vacated alike) are sorted by `start_date` ascending with `created_at` ascending as the tie-break, and the chain is the longest trailing run in which each term's `start_date` falls exactly on the previous term's `end_date` — strict half-open adjacency, where any positive gap breaks the chain. The chain's length becomes the member's `consecutive_terms_served`, and the new term's `chain_index` records its 1-based position in that chain. When the chain length is below the bylaws' `max_consecutive_terms` the member is eligible; when the chain has reached `max_consecutive_terms`, the member is eligible only once the new term's `start_date` falls at least `term_cooloff_years` after the chain's latest `end_date`, with a start exactly cool-off-years after the chain end being eligible, and is otherwise rejected with `ERR_TERM_LIMIT_EXCEEDED`. Finally, unless the member is currently `ACTIVE` — incumbent re-election does not consume a second seat — at least one open seat must exist, else `ERR_NO_SEATS_AVAILABLE`. The open-seat count is the `board_size` of the adopted bylaws minus the count of `ACTIVE` members; electing a member decrements it by exactly 1 and that member's later resignation or removal increments it by exactly 1, so any elect-then-vacate sequence leaves the count identical to its pre-sequence value.

Two structural rules govern the created term. Election requires an `ADOPTED` bylaws to exist, else `ERR_BYLAWS_NOT_ADOPTED`, and the term is version-pinned to that document via its `bylaws_id`: its `end_date` is computed as the `start_date` plus the pinned bylaws' `term_length_years` on the same calendar day, and later amendments never mutate an existing term's end date. The new term must also respect the half-open interval rule of §2.8 against the member's other non-`VACATED` terms, else `ERR_TERM_OVERLAP`. A term whose `start_date` lies in the future is `SCHEDULED`; one whose start has been reached is `ACTIVE` immediately, and a term whose `end_date` has also already passed is swept to `COMPLETED` by the next compliance sweep. Election moves a `PROPOSED`, `PAST`, or `TERM_LIMITED_OUT` member to `ACTIVE` — an `ACTIVE` incumbent simply stays `ACTIVE` — and for a `TERM_LIMITED_OUT` member the new term restarts the chain at `chain_index` 1. Thereafter the sweep advances `SCHEDULED` terms to `ACTIVE` once the clock reaches the start date and completes `ACTIVE` terms at their end; at completion, the member becomes `PAST` if still eligible for re-election (chain length below the cap) or `TERM_LIMITED_OUT` when the chain has reached the current bylaws' `max_consecutive_terms`, and either way the freed seat re-enters the open-seat pool.

Departure mid-service is explicit. Resignation — recorded by a `GovernanceAdmin` or `BoardChair` for anyone, or by the director themself under the self-service rule of §2.1 — moves an `ACTIVE` member to `RESIGNED` and fires the departure chain of §2.10: the member's scheduled or active term becomes `VACATED`, active appointments end with `ended_reason` `RESIGNED`, committees that fall below minimum go `DORMANT` with their scheduled meetings cancelled, and the seat frees. Removal for cause is a `BoardChair`-only act requiring a non-empty `reason` (an empty one is rejected with `ERR_INVALID_REQUEST`) and an `ACTIVE` target (else `ERR_INVALID_STATE`); it moves the member to `REMOVED` and fires the identical cascade with `ended_reason` `REMOVED`.

The **recruitment matrix** is a computed read over the roster, available to every role: for each of the eight skill tags it reports how many `ACTIVE` members hold it (`by_skill`), which skills no `ACTIVE` member covers (`uncovered_skills`), the count of `ACTIVE` members (`active_members`), the adopted bylaws' `board_size`, and the resulting `open_seats` — the skills-based view of the same seat arithmetic the election gates enforce.

### 3.3. Committees and Appointments

Committees are chartered by a `GovernanceAdmin` or `BoardChair` with a `name` unique within the nonprofit among committees that are not `DISSOLVED` (`ERR_DUPLICATE_COMMITTEE_NAME`), a `type` of `AUDIT`, `FINANCE`, `GOVERNANCE`, `NOMINATING`, `EXECUTIVE`, `COMPENSATION`, or `OTHER`, a `min_members` of at least 1, an `authorized_size` no smaller than `min_members`, and a `requires_all_independent` flag defaulting to false — but forced to true whenever the type is `AUDIT`, since audit committees must be composed entirely of independent directors. A new committee is `CHARTERED` and tracks its `active_member_count` of active appointments.

The `BoardChair` staffs a committee by appointing directors. Appointment gates, all evaluated before the seat is granted: the appointee must be an `ACTIVE` member (`ERR_MEMBER_NOT_ELIGIBLE`); the committee must not be `DISSOLVED` (a dissolved committee rejects the appointment with `ERR_INVALID_STATE`); the committee's `active_member_count` must be below its `authorized_size` (`ERR_COMMITTEE_FULL`); a `requires_all_independent` committee accepts only appointees whose `is_independent` is true (`ERR_COMMITTEE_NOT_INDEPENDENT`); and the appointee must hold a reviewed current-fiscal-year disclosure — one in `CLEARED` or `RESTRICTIONS_IMPOSED` — and, when that disclosure is `RESTRICTIONS_IMPOSED`, its `restriction_categories` must not map onto the committee's type, else `ERR_COI_REVIEW_REQUIRED`. Two uniqueness rules complete the gate: a member may not hold two active appointments on the same committee (`ERR_DUPLICATE_APPOINTMENT`), and each appointment carries a `committee_role` of `CHAIR` or `MEMBER` (default `MEMBER`) with at most one active `CHAIR` appointment per committee (`ERR_DUPLICATE_COMMITTEE_CHAIR`). A successful appointment is `ACTIVE` and increments the committee's `active_member_count` by 1; when the committee was `DORMANT` and the restored count reaches at least `min_members`, the committee automatically returns to `ACTIVE` — the restoring appointment itself having passed every gate above.

Activation is a separate, deliberate step: the `BoardChair` activates a `CHARTERED` committee only when its `active_member_count` is at least `min_members` (`ERR_COMMITTEE_BELOW_MIN`), when every active appointee is independent if the committee requires it (`ERR_COMMITTEE_NOT_INDEPENDENT`), and when every active appointee holds a current-fiscal-year disclosure in `CLEARED` or `RESTRICTIONS_IMPOSED` (`ERR_COI_REVIEW_REQUIRED`). The committee lifecycle is `CHARTERED` to `ACTIVE`, with demotion to `DORMANT` whenever an appointment ends and the count of an `ACTIVE` committee falls below `min_members` — a demotion that also cancels the committee's `SCHEDULED` meetings — and recovery from `DORMANT` to `ACTIVE` as described above. An appointment's lifecycle is simply `ACTIVE` to the terminal `ENDED`, with `ended_reason` null while active and recording the cause at the end. The `BoardChair` may end any appointment manually, which moves it to `ENDED` with `ended_reason` `MANUAL` and recomputes the count with the same possible demotion; system-driven endings stamp `RESIGNED`, `REMOVED`, `COI_RESTRICTION`, or `COMMITTEE_DISSOLVED` per their triggering cascade. Dissolution is available from `CHARTERED`, `ACTIVE`, or `DORMANT`: from `CHARTERED` or `ACTIVE` it ends every active appointment with `ended_reason` `COMMITTEE_DISSOLVED` and cancels the committee's scheduled meetings, while from `DORMANT` only the meeting cancellation remains, its appointments having already ended. `DISSOLVED` is terminal.

### 3.4. Meetings, Quorum, and Minutes

A `GovernanceAdmin` or `BoardChair` convenes a meeting by supplying `nonprofit_id`, an optional `committee_id` (absent or null means a full-board meeting), the `scheduled_start` in UTC, a `duration_minutes` greater than 0, an optional `notice_sent_at` recording when notice went out, and an optional `notice_waived` flag defaulting to false. The meeting is born `SCHEDULED`; scheduling enforces the thirty-minute buffered exclusion of §2.8 within the meeting's scope (`ERR_MEETING_OVERLAP`). Bylaws-level notice discipline is checked not at scheduling but at call to order: unless `notice_waived` is true, the `notice_sent_at` must fall at least seven days before the `scheduled_start`, else the call is rejected with `ERR_NOTICE_INSUFFICIENT`.

Calling a meeting to order is the `BoardChair`'s act and performs the quorum determination. The clock must have reached the `scheduled_start` (`ERR_MEETING_TOO_EARLY`), the notice rule above must hold, and a committee meeting additionally requires the committee to be `ACTIVE` (`ERR_COMMITTEE_NOT_ACTIVE`). The caller supplies the `attendance` roster of member ids present. The eligible scope is, for a board meeting, every `ACTIVE` member of the nonprofit, and for a committee meeting, every `ACTIVE` member holding an `ACTIVE` appointment on that committee; the present count is the number of distinct roster ids that fall inside the eligible scope. The denominator follows the adopted bylaws' `quorum_basis`: under `SEATED` it is the count of eligible scope members at call time, so vacancies shrink the requirement, while under `AUTHORIZED` it is the fixed seat count — the bylaws' `board_size` for a board meeting or the committee's `authorized_size` for a committee meeting — so vacancies do not shrink the requirement, and the same attendance can pass under one basis and fail under the other. The `quorum_required` is the `quorum_pct` fraction of that base, rounded up to a whole seat with exact halves rounding up, and quorum is met when the present count is at least the requirement — equality passes — else the call is rejected with `ERR_QUORUM_NOT_MET`. A successful call persists `attendance`, `quorum_base`, `quorum_required`, and `quorum_met` onto the meeting and moves it to `IN_SESSION`.

Adjournment, again by the `BoardChair`, moves the meeting to `ADJOURNED` and settles the floor: every motion of the meeting still `VOTING_OPEN` or `TABLED` is set to `TABLED` with its recorded votes preserved. A `SCHEDULED` meeting may instead be cancelled to `CANCELLED` by a `GovernanceAdmin` or `BoardChair`, and the same cancellation arrives system-side when a committee demotion or dissolution cascade strikes. `MINUTES_APPROVED` and `CANCELLED` are the terminal states.

Minutes are drafted by a `GovernanceAdmin` under the optimistic-concurrency guard of §2.6: each recording must carry `expected_meeting_version` and the `minutes_text` body. The first recording moves an `ADJOURNED` meeting to `MINUTES_DRAFTED`; a later recording stays in `MINUTES_DRAFTED` and replaces the draft; either way the meeting records the caller as `minutes_recorded_by` and its `version` increments by 1. Approval happens at a later sitting of the same body: the `BoardChair` approves the draft by reference to an `approving_meeting_id`, which must name a different meeting of the same scope — the same nonprofit and the same `committee_id`, with both null counting as the same scope — that is currently `IN_SESSION`, else `ERR_MINUTES_APPROVAL_MEETING_INVALID`; segregation of duties additionally forbids the minutes' recorder from approving them, so the approver's `X-User-ID` must differ from `minutes_recorded_by` (`ERR_SEGREGATION_OF_DUTIES`). Approval moves the minutes to `MINUTES_APPROVED`. Rejection follows the same meeting-validity rule via `rejecting_meeting_id` (`ERR_MINUTES_APPROVAL_MEETING_INVALID`) and sends the meeting back to `ADJOURNED`, clearing both `minutes_text` and `minutes_recorded_by` so the draft must be re-created — the deliberate `ADJOURNED`-to-`MINUTES_DRAFTED` cycle that lets a board correct its record across sittings.

### 3.5. Motions, Voting, and Governance Outcomes

Business reaches the floor as a motion introduced by a `BoardChair` or `BoardDirector` with `nonprofit_id`, the `meeting_id` of its meeting, a `title`, and a `category` of `GOVERNANCE`, `FINANCE`, `PERSONNEL`, `POLICY`, `BYLAWS`, `FUNDRAISING`, or `OTHER`. Two optional knobs govern ordinary motions: `threshold` — `SIMPLE_MAJORITY` (the default), `TWO_THIRDS`, or `UNANIMOUS` — and `threshold_basis` — `PRESENT_AND_VOTING` (the default), `FULL_QUORUM`, or `FULL_BOARD`. Category rules override the generic shape. A `BYLAWS` motion must carry the `bylaws_amendment_id` of a `PROPOSED` amendment (`ERR_AMENDMENT_NOT_PROPOSED`), no other non-terminal motion may already reference that amendment (`ERR_AMENDMENT_HAS_OPEN_MOTION`), the amendment's `motion_id` is set to the new motion, and the `threshold` and `threshold_basis` inputs are ignored because the amendment-adoption threshold governs passage. A `POLICY` motion must carry a `policy_title`. A `FUNDRAISING` motion may not be introduced at all while the organization's `compliance_posture` is `NON_COMPLIANT` (`ERR_NONCOMPLIANT_POSTURE_BLOCKS`). A new motion is `INTRODUCED`.

The `BoardChair` drives the floor. Opening voting requires an `INTRODUCED` motion whose meeting is `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`) and moves the motion to `VOTING_OPEN`. Tabling is available from `INTRODUCED` or `VOTING_OPEN`; resuming returns a `TABLED` motion to `VOTING_OPEN` and likewise requires the meeting to be in session — the `VOTING_OPEN`-to-`TABLED`-to-`VOTING_OPEN` cycle is the normal way business survives an adjournment, since adjournment tables everything left open. Withdrawal is available from `INTRODUCED` or `TABLED` and moves the motion to `WITHDRAWN`; withdrawing a bylaws motion also frees the amendment's motion link. `PASSED`, `FAILED`, and `WITHDRAWN` are terminal.

Directors vote as themselves per §2.1, supplying `nonprofit_id`, `motion_id`, their own `board_member_id`, and a `choice` of `AYE`, `NAY`, `ABSTAIN`, or `RECUSED`. The motion must be `VOTING_OPEN` (`ERR_MOTION_NOT_OPEN`) and its meeting `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`). The voter must be eligible: an `ACTIVE` member, present on the meeting's persisted `attendance` roster, and — for a committee meeting — holding an `ACTIVE` appointment on that committee, else `ERR_VOTER_NOT_ELIGIBLE`. Each member votes at most once per motion (`ERR_DUPLICATE_VOTE`), and votes are immutable once recorded. Recusal is enforced, not advisory: a voter whose current-fiscal-year disclosure is `RESTRICTIONS_IMPOSED` with `restriction_categories` containing the motion's `category` must cast `RECUSED`, and any other choice is rejected with `ERR_MEMBER_RECUSED`. After each cast the motion's tallies — `votes_for`, `votes_against`, `votes_abstain`, `votes_recused` — are recomputed from the vote rows, which, the record being append-only, makes every recount deterministic.

Closing the vote, again the `BoardChair`'s act with the same in-session requirement, fixes the outcome. The four tallies are recounted from the vote rows at close, and the basis depends on the motion's `threshold_basis`: under `PRESENT_AND_VOTING` the basis is the sum of `AYE` and `NAY` votes, with abstentions and recusals excluded; under `FULL_QUORUM` it is the meeting's persisted `quorum_required`; under `FULL_BOARD` it is the count of the nonprofit's `ACTIVE` members at close time minus the recusal count. The required votes follow the `threshold`: a simple majority needs the basis halved and rounded down, plus one; a two-thirds threshold needs the ceiling of two-thirds of the basis — so a basis of five requires four; unanimity needs the full basis and additionally that no `NAY` and no `ABSTAIN` votes exist. The motion passes when the `AYE` count is at least the requirement — equality passes — with the additional unanimous-condition applied for `UNANIMOUS`, and fails otherwise; the computed requirement is persisted as the motion's `required_votes`, which is null until close.

Two categories carry passage cascades. When a `POLICY` motion passes, the entry of `policy_title`, `motion_id`, and the adoption timestamp `adopted_at` is appended to the nonprofit's `adopted_policies` register and the nonprofit's `version` increments by 1. When a `BYLAWS` motion closes, the generic threshold machinery is replaced by the amendment-adoption threshold: the basis is the count of `ACTIVE` directors when that count is at least three-quarters of the authorized seats — computed as the ceiling of 0.75 times `board_size` — and otherwise the full `board_size` itself, so a healthy board needs the bylaws' percentage of seated directors while a depleted board needs that percentage of authorized seats; the required votes are the greater of 2 and the ceiling of `amendment_threshold_pct` percent of that basis. Passage moves the linked amendment to `ADOPTED` and fires the adoption chain: a successor bylaws document is minted with `version_no` one greater than the base, the base's field values overlaid with the amendment's `proposed_fields`, status `ADOPTED`, and `adopted_at` stamped from the clock; the base document becomes `SUPERSEDED`; existing terms remain pinned to their original documents, but every future election reads `term_length_years`, `max_consecutive_terms`, and `board_size` from the newly adopted document; and the nonprofit's `version` increments by 1. Failure moves the amendment to `DEFEATED` and clears its `motion_id`, leaving it free to be revised and re-voted.

### 3.6. Conflict-of-Interest Disclosure and Restrictions

Each director files one disclosure per fiscal year, as themself per §2.1, supplying `nonprofit_id`, their own `board_member_id`, the `fiscal_year` covered, and an `answers` list of question entries — each with a `question_key`, a boolean `answer`, and an optional free-text `detail`. A second filing for the same member and fiscal year is rejected with `ERR_DUPLICATE_DISCLOSURE`, and an empty `answers` list with `ERR_INVALID_REQUEST`. The filing is `FILED` upon receipt, its `filed_at` stamped from the clock, and its `has_conflict` flag is true when any answer is answered true.

Review is peer review under segregation of duties. A reviewer — a `BoardChair`, `BoardDirector`, or `Treasurer` — begins review of a `FILED` disclosure, which moves it to `UNDER_REVIEW` and records the caller as `reviewer_member_id`. The reviewer may not be the filer (`ERR_SEGREGATION_OF_DUTIES`), must be an `ACTIVE` member of the same nonprofit (`ERR_REVIEWER_NOT_QUALIFIED`), and must have filed their own disclosure for the same fiscal year in any of `FILED`, `UNDER_REVIEW`, `CLEARED`, or `RESTRICTIONS_IMPOSED` (`ERR_REVIEWER_NOT_COMPLIANT`). Only the assigned reviewer may then decide the review: clearing moves the disclosure to `CLEARED`, while imposing restrictions requires a non-empty `restriction_categories` list (`ERR_INVALID_REQUEST`) and moves it to `RESTRICTIONS_IMPOSED`; either act attempted by anyone other than the recorded `reviewer_member_id` is rejected with `ERR_REVIEWER_MISMATCH`.

Imposing restrictions fires the restriction chain of §2.10. The member's `has_active_restrictions` becomes true (link 1); the member's active appointments on committees whose type maps to a restricted category end with `ended_reason` `COI_RESTRICTION` — a `FINANCE` restriction maps to `FINANCE`, `AUDIT`, and `COMPENSATION` committees, a `PERSONNEL` restriction to `COMPENSATION` and `EXECUTIVE` committees, and a `GOVERNANCE` restriction to `GOVERNANCE` and `NOMINATING` committees (link 2); and each affected committee recomputes its count, demoting to `DORMANT` with its scheduled meetings cancelled where the minimum is breached (link 3). The same reviewer may later lift the restrictions — again, anyone else is rejected with `ERR_REVIEWER_MISMATCH` — which moves the disclosure to `CLEARED`, clears the `restriction_categories`, and recomputes `has_active_restrictions` to false, the one-disclosure-per-year uniqueness guaranteeing no second current-year restricted disclosure could keep it true. `CLEARED` is terminal. Disclosure delinquency — a missing or unreviewed current-year disclosure lingering past ninety days into the fiscal year — feeds the compliance posture in §3.9.

### 3.7. Executive Evaluation and Succession Planning

Once per fiscal year the board evaluates its executive: a `BoardChair` opens an evaluation with `nonprofit_id`, the `fiscal_year` under review, and the `executive_name`; a duplicate for the same nonprofit and year is rejected with `ERR_DUPLICATE_EVALUATION`. The evaluation is born `DRAFT` and will run `DRAFT` to `COMMITTEE_REVIEW` to `RATIFIED` to `DELIVERED`, with a return-to-`DRAFT` loop for rework. The score sheet covers five dimensions — `LEADERSHIP`, `FUNDRAISING`, `FINANCIAL`, `PROGRAM`, and `GOVERNANCE` — each scored as an integer from 1 to 5, and an empty or incomplete sheet cannot advance.

Score entry is a guarded write per §2.6: a `BoardChair`, `BoardDirector`, or `Treasurer` submits the `scores` list together with `expected_evaluation_version`. The first score edit locks in its recorder as `recorded_by_user_id`, and every later edit while the evaluation remains in `DRAFT` must come from that same user, else `ERR_EVALUATION_RECORDER_MISMATCH`; each accepted edit replaces the sheet, recomputes the `provisional_composite`, and increments the evaluation's `version` by 1. The provisional figure is the committee's working number: the unweighted mean of all recorded scores, rounded half-up to 2 decimal places. When the sheet is complete — all five dimensions present, else `ERR_EVALUATION_INCOMPLETE` — the `BoardChair` submits it to committee review, moving the evaluation to `COMMITTEE_REVIEW`. The committee may send it back to `DRAFT` for rework, after which the provisional composite is recomputed on the next score edit, or advance it to ratification.

Ratification produces the board-final number. A `BoardChair` or `Treasurer` ratifies, but never the score recorder — the ratifier's `X-User-ID` must differ from `recorded_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — and the ratifier is recorded as `ratified_by_user_id`. At ratification the `final_composite` is computed as the weighted sum of the five dimension scores — `LEADERSHIP` weighted 0.30, `FUNDRAISING` 0.20, `FINANCIAL` 0.20, `PROGRAM` 0.20, and `GOVERNANCE` 0.10 — rounded half-up to 2 decimal places, and the `rating` band is `EXCEEDS` when the final composite is at least 4.25, `MEETS` when at least 3.00, `NEEDS_IMPROVEMENT` when at least 2.00, and `UNSATISFACTORY` below that. Both `final_composite` and `rating` are null until ratified. The two variants genuinely differ on identical inputs: scores of 5, 5, 5, 1, 1 yield a provisional composite of 3.40 but a final composite of 3.80. Finally the `BoardChair` delivers the ratified evaluation to the executive, moving it to `DELIVERED`; the `ExecutiveDirector` role itself is excluded from every write in this workflow.

Succession planning runs in parallel. A `BoardChair` or `GovernanceAdmin` drafts a plan with `nonprofit_id`, a `target_role` of `EXECUTIVE_DIRECTOR`, `BOARD_CHAIR`, or `TREASURER`, a `readiness` of `READY_NOW`, `ONE_YEAR`, or `TWO_PLUS_YEARS`, and optionally the interim designee fields. Approval is the gated step: the plan must be `DRAFT`, and the designee must be present per the target role — for `BOARD_CHAIR` or `TREASURER` an `interim_designee_member_id` referencing an `ACTIVE` member of the nonprofit, for `EXECUTIVE_DIRECTOR` a non-empty free-text `interim_designee_name` since non-board staff may serve as interim — and an absent designee is rejected with `ERR_DESIGNEE_REQUIRED` while an unresolvable member reference surfaces as `ERR_NOT_FOUND`. At most one plan per nonprofit and target role may stand approved or activated at a time: approval moves the draft to `APPROVED` and automatically supersedes any previously `APPROVED` plan for the same pairing, moving it to `SUPERSEDED`. From `APPROVED` the `BoardChair` may activate the plan in an emergency transition to `ACTIVATED`, stand an activated plan back down to `APPROVED` — the activate-stand-down loop — or return the plan to `DRAFT` for revision; a `DRAFT` plan may be discarded to `DISCARDED`, and `SUPERSEDED` and `DISCARDED` are terminal.

### 3.8. Form 990 Filings and Public Disclosure

The annual information return begins as a draft created by a `Treasurer` or `GovernanceAdmin` with `nonprofit_id`, the `fiscal_year` filed, `total_revenue_cents`, `total_expenses_cents`, `contributions_cents`, `program_service_revenue_cents`, and the `preparer_user_id` of whoever prepared it. One root filing exists per nonprofit and fiscal year — a second root is rejected with `ERR_DUPLICATE_FILING` — while amendment filings carry a `supersedes_filing_id` pointing at the filing they replace, whose status must be `FILED` or `PUBLIC_DISCLOSED`, and are exempt from the uniqueness rule. At creation the system derives three fields: `net_change_cents` as total revenue minus total expenses; `public_support_ratio` as contributions divided by total revenue rounded half-up to 4 decimal places, defined as 0 when total revenue is zero; and `filing_due_date` from the fiscal calendar — the last day of the `fiscal_year_end_month` in the filing's fiscal year, then the first day of the following month, then four months and fourteen days forward, so a December year-end yields a May 15 deadline and a June year-end yields November 15. A draft may be discarded to `DISCARDED` by the `Treasurer`.

Routing the draft to the board — a `Treasurer` or `GovernanceAdmin` act — requires an `ADOPTED` bylaws to measure coverage against (`ERR_BYLAWS_NOT_ADOPTED`), fixes the `review_required_count` as the ceiling of the bylaws' `quorum_pct` fraction of the `ACTIVE` member count on the `SEATED` basis regardless of the bylaws' own `quorum_basis`, and moves the filing to `IN_BOARD_REVIEW`. Directors then record their reviews as themselves: each review appends the caller's `X-User-ID` to `reviewed_by_member_ids`, the reviewer must be an `ACTIVE` member, and a member reviews a filing at most once (`ERR_DUPLICATE_REVIEW`). Approval is the `BoardChair`'s act under two gates: the approver must differ from the `preparer_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and the count of recorded reviews must be at least the `review_required_count` (`ERR_REVIEW_COVERAGE_INSUFFICIENT`) — where reviews count only from members still `ACTIVE` at approve time, reviews by since-departed members being dropped from the count. Approval records `approved_by_user_id` and moves the filing to `APPROVED`.

Marking the filing as filed with the IRS — by the `Treasurer` or `GovernanceAdmin` — stamps `filed_on` from the clock, computes `filed_late` as true only when the filing date falls strictly after the `filing_due_date` (filing exactly on the due date is timely), and moves the filing to `FILED`; when the filing is an amendment, its superseded target moves from `FILED` or `PUBLIC_DISCLOSED` to `SUPERSEDED` in the same act. The public-disclosure obligation is then tracked: a filing that remains `FILED` while the clock passes thirty days after its `filed_on` has `disclosure_overdue` true, and recording the public posting — by a `GovernanceAdmin` or `ComplianceOfficer` — stamps `public_disclosure_posted_at`, recomputes `disclosure_overdue` to false, and moves the filing to its terminal `PUBLIC_DISCLOSED` state.

### 3.9. State Registrations, Insurance, and the Compliance Posture

Charitable solicitation authority is tracked per jurisdiction. A `ComplianceOfficer` creates a registration with `nonprofit_id`, a two-letter `state_code` unique within the nonprofit (`ERR_DUPLICATE_REGISTRATION`), an optional `renewal_cycle_months` defaulting to 12, the `current_period_end` at which the current authority expires, and an optional `contributions_in_state_cents` recording the most recent actual in-state contributions — leaving it null forces the estimated fee variant described below. A new registration is `REGISTERED`, and its lifecycle loops `REGISTERED` to `RENEWAL_DUE` to `RENEWAL_SUBMITTED` and back to `REGISTERED`, with `LAPSED` reachable from every state and no terminal state at all.

The sweep drives the calendar edges: a registration within sixty days of its period end — clock at or after sixty days before the end but still before it — becomes `RENEWAL_DUE`; one whose period end has passed becomes `LAPSED`, including a submitted-but-unconfirmed renewal whose period expired anyway. The lapse fires the lapse chain of §2.10: the organization's posture is driven to `NON_COMPLIANT` while any registration is `LAPSED` (link 1), and that posture change withdraws every fundraising motion of the nonprofit still `INTRODUCED`, `VOTING_OPEN`, or `TABLED` (link 2).

Renewal submission is a paid act by the `ComplianceOfficer`. From `REGISTERED` the window opens ninety days before the period end — submitting earlier is rejected with `ERR_RENEWAL_TOO_EARLY` — and from `RENEWAL_DUE` submission is already timely; a submission from any other state is rejected with `ERR_INVALID_STATE`. The payload's `paid_fee_cents` must equal the fee the system computes for the registration (`ERR_RENEWAL_FEE_MISMATCH`). That fee prices off an effective contribution base in cents: when the submission supplies `contributions_in_state_cents` the **actual** variant prices from that figure — and the payload value is persisted on the registration — while an omitted figure falls back to the **estimated** variant, ten percent of the nonprofit's `annual_gross_receipts_cents` rounded half-up to whole cents, the same variant used for pre-submission previews of registrations whose contributions are null. The base then maps into a four-rung ladder whose boundaries belong to the lower rung: at most $25,000 (2,500,000 cents) pays a $50 base; above that and at most $100,000 pays $150; above that and at most $500,000 pays $300; and above $500,000 pays a $500 base plus an overage surcharge of $10 for every started $1,000 increment by which the base exceeds $500,000 — the surcharge ceiled to whole increments before any other rounding, per the pinned order of §2.9. The computed fee is persisted as `renewal_fee_cents`, and the registration moves to `RENEWAL_SUBMITTED`. Confirmation that the jurisdiction accepted the renewal rolls `current_period_end` forward by `renewal_cycle_months`, returns the registration to `REGISTERED`, and recomputes the posture, closing the renewal loop. Reinstatement from `LAPSED` follows the same fee machinery with a late fee of ten percent of the base-plus-surcharge subtotal, rounded half-up to whole cents, added on top; it resets `current_period_end` to the clock date plus `renewal_cycle_months`, persists the fee including the late component, and recomputes the posture, which may lift the organization out of `NON_COMPLIANT`.

Risk oversight tracks the organization's insurance portfolio. A `ComplianceOfficer` quotes a policy with `nonprofit_id`, a `policy_type` of `DNO` or `GENERAL_LIABILITY`, the `carrier`, a `coverage_limit_cents`, an annual `premium_cents`, the `policy_start_date` and `policy_end_date` delimiting the half-open coverage interval (an end not after the start is rejected with `ERR_INVALID_REQUEST`), an optional `prior_policy_id` chaining a renewal to the policy it replaces — which triggers the `gap_days` computation of §2.8 at bind — and an `acknowledge_gap` flag defaulting to false. A quote is `QUOTED`. Binding enforces the coverage floor and the interval rules: the limit must be at least the ceiling of one quarter of the nonprofit's `annual_gross_receipts_cents` (`ERR_COVERAGE_BELOW_FLOOR`); a renewal with a negative gap is an overlap (`ERR_POLICY_OVERLAP`), and one with a positive gap requires `acknowledge_gap` to be true (`ERR_COVERAGE_GAP`); and the interval must not overlap any non-terminal policy of the same organization and type (`ERR_POLICY_OVERLAP`). Activation is allowed only once the clock has reached the `policy_start_date` (`ERR_POLICY_NOT_YET_EFFECTIVE`) and moves the policy to `ACTIVE` with a posture recompute. The sweep expires an `ACTIVE` policy at its `policy_end_date` to `EXPIRED`, and for a `DNO` policy with no other active D&O coverage spanning the clock date the posture falls to `NON_COMPLIANT`. Cancellation behaves per state: a `QUOTED` policy cancels quietly, a `BOUND` policy's cancellation recomputes the posture since coverage may no longer be in force, and a mid-term `ACTIVE` cancellation recomputes the posture with the same D&O lapse to `NON_COMPLIANT` when no other active D&O policy covers the date. `EXPIRED` and `CANCELLED` are terminal.

All of these threads converge in the organization's `compliance_posture`, recomputed by the sweep and by every registration, filing, policy, and disclosure transition that feeds it. The posture is `NON_COMPLIANT` when any of the following holds: a registration stands `LAPSED`; the prior fiscal year's Form 990 obligation is past due, meaning the fiscal year before the `current_fiscal_year` has no filing in `FILED`, `PUBLIC_DISCLOSED`, or `SUPERSEDED` while the clock has passed that filing's `filing_due_date`; or no `ACTIVE` `DNO` policy covers the clock date. Failing that, the posture is `AT_RISK` when any of the following holds: a registration stands `RENEWAL_DUE` or `RENEWAL_SUBMITTED`; a filing's `disclosure_overdue` is true; the active D&O policy's `policy_end_date` falls within thirty days of the clock with no `BOUND` or `ACTIVE` successor whose `policy_start_date` falls on or before the current policy's end; or at least one `ACTIVE` member's current-fiscal-year disclosure is missing or still `FILED` or `UNDER_REVIEW` more than ninety days into the fiscal year. Otherwise the posture is `COMPLIANT`. The posture is not merely informational: while it is `NON_COMPLIANT`, introducing a `FUNDRAISING` motion is rejected with `ERR_NONCOMPLIANT_POSTURE_BLOCKS`, and the lapse cascade of §2.10 withdraws the ones already in flight.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource, record an action against it, or read data return `200 OK`. Request and response payloads for each endpoint are reconstructed from the workflow narratives of §3 together with the global rules of §2; the table below is the routing and authorization contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/boardgov/_clock/set_current_utc` | Advance the test-driving logical clock | GovernanceAdmin |
| POST | `/boardgov/nonprofits` | Incorporate a nonprofit | GovernanceAdmin |
| GET | `/boardgov/nonprofits/{id}` | Get a nonprofit with computed fiscal year and posture | All roles |
| PATCH | `/boardgov/nonprofits/{id}` | Update nonprofit profile fields (OCC-guarded) | GovernanceAdmin |
| POST | `/boardgov/nonprofits/{id}/compliance_sweep` | Apply every time-based transition as of the logical clock | GovernanceAdmin, ComplianceOfficer |
| GET | `/boardgov/nonprofits/{id}/recruitment-matrix` | Computed skills matrix and seat utilization | All roles |
| POST | `/boardgov/bylaws` | Draft founding bylaws | GovernanceAdmin |
| GET | `/boardgov/bylaws/{id}` | Get a bylaws document | All roles |
| GET | `/boardgov/bylaws` | List bylaws documents (filtered) | All roles |
| POST | `/boardgov/bylaws/{id}/adopt` | Adopt a draft bylaws (founding adoption) | GovernanceAdmin |
| POST | `/boardgov/bylaws/{id}/discard` | Discard a draft bylaws | GovernanceAdmin |
| POST | `/boardgov/bylaws-amendments` | Draft an amendment against an adopted bylaws | BoardChair, BoardDirector, GovernanceAdmin |
| GET | `/boardgov/bylaws-amendments/{id}` | Get an amendment | All roles |
| GET | `/boardgov/bylaws-amendments` | List amendments (filtered) | All roles |
| POST | `/boardgov/bylaws-amendments/{id}/propose` | Put a draft amendment before the board | BoardChair |
| POST | `/boardgov/bylaws-amendments/{id}/revise` | Return a defeated amendment to draft | BoardChair |
| POST | `/boardgov/bylaws-amendments/{id}/withdraw` | Withdraw a draft or proposed amendment | BoardChair |
| POST | `/boardgov/board-members` | Propose a director nominee | GovernanceAdmin |
| GET | `/boardgov/board-members/{id}` | Get a board member | All roles |
| GET | `/boardgov/board-members` | List board members (filtered; skills queries) | All roles |
| PATCH | `/boardgov/board-members/{id}` | Update member profile and officer designation | GovernanceAdmin |
| POST | `/boardgov/board-members/{id}/resign` | Record a director's resignation (staff/chair; directors self-only) | GovernanceAdmin, BoardChair, BoardDirector, Treasurer |
| POST | `/boardgov/board-members/{id}/remove` | Remove a director for cause | BoardChair |
| POST | `/boardgov/board-terms` | Elect a member to a bylaws-pinned term | BoardChair, GovernanceAdmin |
| GET | `/boardgov/board-terms/{id}` | Get a board term | All roles |
| GET | `/boardgov/board-terms` | List board terms (filtered) | All roles |
| POST | `/boardgov/committees` | Charter a committee | GovernanceAdmin, BoardChair |
| GET | `/boardgov/committees/{id}` | Get a committee | All roles |
| GET | `/boardgov/committees` | List committees (filtered) | All roles |
| POST | `/boardgov/committees/{id}/activate` | Activate a chartered committee (membership gates) | BoardChair |
| POST | `/boardgov/committees/{id}/dissolve` | Dissolve a committee (ends appointments, cancels meetings) | BoardChair |
| POST | `/boardgov/committee-appointments` | Appoint an active director to a committee | BoardChair |
| GET | `/boardgov/committee-appointments/{id}` | Get an appointment | All roles |
| GET | `/boardgov/committee-appointments` | List appointments (filtered) | All roles |
| POST | `/boardgov/committee-appointments/{id}/end` | End an appointment manually | BoardChair |
| POST | `/boardgov/meetings` | Schedule a board or committee meeting | GovernanceAdmin, BoardChair |
| GET | `/boardgov/meetings/{id}` | Get a meeting | All roles |
| GET | `/boardgov/meetings` | List meetings (filtered) | All roles |
| POST | `/boardgov/meetings/{id}/call_to_order` | Call a scheduled meeting to order (quorum check) | BoardChair |
| POST | `/boardgov/meetings/{id}/adjourn` | Adjourn an in-session meeting | BoardChair |
| POST | `/boardgov/meetings/{id}/cancel` | Cancel a scheduled meeting | GovernanceAdmin, BoardChair |
| POST | `/boardgov/meetings/{id}/minutes` | Record or replace draft minutes (OCC-guarded) | GovernanceAdmin |
| POST | `/boardgov/meetings/{id}/approve_minutes` | Approve draft minutes at a later same-scope sitting | BoardChair |
| POST | `/boardgov/meetings/{id}/reject_minutes` | Reject draft minutes back for redrafting | BoardChair |
| POST | `/boardgov/motions` | Introduce a motion onto a meeting's floor | BoardChair, BoardDirector |
| GET | `/boardgov/motions/{id}` | Get a motion | All roles |
| GET | `/boardgov/motions` | List motions (filtered) | All roles |
| POST | `/boardgov/motions/{id}/open_voting` | Open the floor vote on an introduced motion | BoardChair |
| POST | `/boardgov/motions/{id}/close_voting` | Close the vote and compute the outcome | BoardChair |
| POST | `/boardgov/motions/{id}/table` | Table a motion | BoardChair |
| POST | `/boardgov/motions/{id}/resume` | Resume a tabled motion | BoardChair |
| POST | `/boardgov/motions/{id}/withdraw` | Withdraw an introduced or tabled motion | BoardChair |
| POST | `/boardgov/votes` | Cast a vote (self-service; immutable) | BoardDirector, BoardChair, Treasurer |
| GET | `/boardgov/votes/{id}` | Get a vote record | All roles |
| GET | `/boardgov/votes` | List votes (filtered) | All roles |
| POST | `/boardgov/coi-disclosures` | File an annual conflict-of-interest disclosure | BoardDirector, BoardChair, Treasurer |
| GET | `/boardgov/coi-disclosures/{id}` | Get a disclosure | All roles |
| GET | `/boardgov/coi-disclosures` | List disclosures (filtered) | All roles |
| POST | `/boardgov/coi-disclosures/{id}/start_review` | Begin peer review of a filed disclosure | BoardChair, BoardDirector, Treasurer |
| POST | `/boardgov/coi-disclosures/{id}/clear` | Reviewer clears a disclosure | BoardChair, BoardDirector, Treasurer |
| POST | `/boardgov/coi-disclosures/{id}/impose_restrictions` | Reviewer imposes voting restrictions | BoardChair, BoardDirector, Treasurer |
| POST | `/boardgov/coi-disclosures/{id}/lift_restrictions` | Reviewer lifts imposed restrictions | BoardChair, BoardDirector, Treasurer |
| POST | `/boardgov/executive-evaluations` | Open an annual executive evaluation | BoardChair |
| GET | `/boardgov/executive-evaluations/{id}` | Get an evaluation | All roles |
| GET | `/boardgov/executive-evaluations` | List evaluations (filtered) | All roles |
| PATCH | `/boardgov/executive-evaluations/{id}/scores` | Enter or revise dimension scores (OCC-guarded) | BoardChair, BoardDirector, Treasurer |
| POST | `/boardgov/executive-evaluations/{id}/submit_review` | Submit the completed score sheet to committee review | BoardChair |
| POST | `/boardgov/executive-evaluations/{id}/return` | Return an evaluation to draft for rework | BoardChair |
| POST | `/boardgov/executive-evaluations/{id}/ratify` | Ratify the evaluation (weighted composite; SoD) | BoardChair, Treasurer |
| POST | `/boardgov/executive-evaluations/{id}/deliver` | Deliver the ratified evaluation to the executive | BoardChair |
| POST | `/boardgov/succession-plans` | Draft a succession plan for a key role | BoardChair, GovernanceAdmin |
| GET | `/boardgov/succession-plans/{id}` | Get a succession plan | All roles |
| GET | `/boardgov/succession-plans` | List succession plans (filtered) | All roles |
| POST | `/boardgov/succession-plans/{id}/approve` | Approve a plan (supersedes the prior approved plan) | BoardChair |
| POST | `/boardgov/succession-plans/{id}/revise` | Return an approved plan to draft | BoardChair |
| POST | `/boardgov/succession-plans/{id}/activate` | Activate an approved plan (emergency transition) | BoardChair |
| POST | `/boardgov/succession-plans/{id}/stand_down` | Stand an activated plan back down to approved | BoardChair |
| POST | `/boardgov/succession-plans/{id}/discard` | Discard a draft plan | BoardChair |
| POST | `/boardgov/form990-filings` | Draft a Form 990 filing (root or amendment) | Treasurer, GovernanceAdmin |
| GET | `/boardgov/form990-filings/{id}` | Get a filing | All roles |
| GET | `/boardgov/form990-filings` | List filings (filtered) | All roles |
| POST | `/boardgov/form990-filings/{id}/submit_for_review` | Route the draft to the board (fixes review requirement) | Treasurer, GovernanceAdmin |
| POST | `/boardgov/form990-filings/{id}/record_review` | Record a director's review of the filing | BoardDirector, BoardChair, Treasurer |
| POST | `/boardgov/form990-filings/{id}/approve` | Approve the reviewed filing (SoD; coverage gate) | BoardChair |
| POST | `/boardgov/form990-filings/{id}/mark_filed` | Mark the approved filing as filed with the IRS | Treasurer, GovernanceAdmin |
| POST | `/boardgov/form990-filings/{id}/post_public_disclosure` | Record public posting of the filed return | GovernanceAdmin, ComplianceOfficer |
| POST | `/boardgov/form990-filings/{id}/discard` | Discard a draft filing | Treasurer |
| POST | `/boardgov/state-registrations` | Register solicitation authority in a jurisdiction | ComplianceOfficer |
| GET | `/boardgov/state-registrations/{id}` | Get a registration | All roles |
| GET | `/boardgov/state-registrations` | List registrations (filtered) | All roles |
| POST | `/boardgov/state-registrations/{id}/submit_renewal` | Submit a renewal with fee payment | ComplianceOfficer |
| POST | `/boardgov/state-registrations/{id}/confirm_renewal` | Confirm the jurisdiction accepted the renewal | ComplianceOfficer |
| POST | `/boardgov/state-registrations/{id}/reinstate` | Reinstate a lapsed registration (late fee) | ComplianceOfficer |
| POST | `/boardgov/insurance-policies` | Quote a D&O or general-liability policy | ComplianceOfficer |
| GET | `/boardgov/insurance-policies/{id}` | Get a policy | All roles |
| GET | `/boardgov/insurance-policies` | List policies (filtered) | All roles |
| POST | `/boardgov/insurance-policies/{id}/bind` | Bind a quote (floor, gap, and overlap checks) | ComplianceOfficer |
| POST | `/boardgov/insurance-policies/{id}/activate` | Activate a bound policy on or after its start date | ComplianceOfficer |
| POST | `/boardgov/insurance-policies/{id}/cancel` | Cancel a policy | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflow it guards in §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_IDENTITY_NOT_QUALIFIED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_BYLAWS_NOT_ADOPTED` | 409 Conflict |
| `ERR_BYLAWS_ALREADY_ADOPTED` | 409 Conflict |
| `ERR_MEETING_NOT_IN_SESSION` | 409 Conflict |
| `ERR_MOTION_NOT_OPEN` | 409 Conflict |
| `ERR_COMMITTEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_AMENDMENT_NOT_PROPOSED` | 409 Conflict |
| `ERR_AMENDMENT_HAS_OPEN_MOTION` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_REVIEWER_NOT_QUALIFIED` | 409 Conflict |
| `ERR_REVIEWER_NOT_COMPLIANT` | 409 Conflict |
| `ERR_REVIEWER_MISMATCH` | 409 Conflict |
| `ERR_EVALUATION_RECORDER_MISMATCH` | 409 Conflict |
| `ERR_MEMBER_RECUSED` | 409 Conflict |
| `ERR_NONCOMPLIANT_POSTURE_BLOCKS` | 409 Conflict |
| `ERR_DUPLICATE_EIN` | 409 Conflict |
| `ERR_DUPLICATE_MEMBER_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_DISCLOSURE` | 409 Conflict |
| `ERR_DUPLICATE_FILING` | 409 Conflict |
| `ERR_DUPLICATE_EVALUATION` | 409 Conflict |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_DUPLICATE_COMMITTEE_NAME` | 409 Conflict |
| `ERR_DUPLICATE_COMMITTEE_CHAIR` | 409 Conflict |
| `ERR_DUPLICATE_APPOINTMENT` | 409 Conflict |
| `ERR_DUPLICATE_VOTE` | 409 Conflict |
| `ERR_DUPLICATE_REVIEW` | 409 Conflict |
| `ERR_MEMBER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_TERM_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_NO_SEATS_AVAILABLE` | 409 Conflict |
| `ERR_COMMITTEE_BELOW_MIN` | 409 Conflict |
| `ERR_COMMITTEE_FULL` | 409 Conflict |
| `ERR_COMMITTEE_NOT_INDEPENDENT` | 409 Conflict |
| `ERR_COI_REVIEW_REQUIRED` | 409 Conflict |
| `ERR_TERM_OVERLAP` | 409 Conflict |
| `ERR_MEETING_OVERLAP` | 409 Conflict |
| `ERR_MEETING_TOO_EARLY` | 409 Conflict |
| `ERR_NOTICE_INSUFFICIENT` | 409 Conflict |
| `ERR_RENEWAL_TOO_EARLY` | 409 Conflict |
| `ERR_COVERAGE_GAP` | 409 Conflict |
| `ERR_POLICY_OVERLAP` | 409 Conflict |
| `ERR_POLICY_NOT_YET_EFFECTIVE` | 409 Conflict |
| `ERR_RENEWAL_FEE_MISMATCH` | 409 Conflict |
| `ERR_COVERAGE_BELOW_FLOOR` | 409 Conflict |
| `ERR_QUORUM_NOT_MET` | 409 Conflict |
| `ERR_REVIEW_COVERAGE_INSUFFICIENT` | 409 Conflict |
| `ERR_EVALUATION_INCOMPLETE` | 409 Conflict |
| `ERR_DESIGNEE_REQUIRED` | 409 Conflict |
| `ERR_MINUTES_APPROVAL_MEETING_INVALID` | 409 Conflict |
| `ERR_VOTER_NOT_ELIGIBLE` | 409 Conflict |
