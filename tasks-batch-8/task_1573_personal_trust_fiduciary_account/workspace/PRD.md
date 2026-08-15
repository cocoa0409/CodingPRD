# Personal Trust Fiduciary API — Product Requirements Document

## 1. Introduction

Bank trust departments administer personal trusts under a fiduciary standard that few other lines of business tolerate: every dollar of a trust must be traceable to either its income account or its principal account, discretionary distributions to beneficiaries must survive committee scrutiny, investment portfolios must be continuously measured against a written policy statement, trustee compensation must be disclosed before it is collected, and the whole arrangement must ultimately be wound down with a final accounting, a final Form 1041, and a defensible per-beneficiary payout. Errors are not merely operational; they expose the bank to surcharge litigation from beneficiaries who are often family members of a deceased grantor.

This document specifies a REST API, mounted under `/trusts`, for administering that full lifecycle: account acceptance and trust-instrument interpretation, discretionary distribution requests with committee voting, investment policy adherence and drift remediation, principal-versus-income ledger accounting, annual beneficiary statements, fiduciary income-tax coordination, trustee fee assessment and disclosure, and termination with final distribution. Seven acting roles collaborate under explicit segregation-of-duties rules, an append-only ledger supplies the single source of truth for every derived balance, and two write operations against a trust are guarded by optimistic concurrency so that a stale view of available funds can never silently overwrite a newer one. The intended reader is the engineer implementing the service; every rule below is contractual.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, pagination, resource conventions, monetary precision, the ledger model, concurrency control, and the order in which the server evaluates competing rejection reasons.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not authorized for the target operation is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly seven roles: `TrustOfficer`, `TrustExecutive`, `InvestmentManager`, `TrustOperationsOfficer`, `TaxSpecialist`, `CommitteeMember`, and `Beneficiary`.

Five of these roles are opaque operator identities. When `X-User-Role` is `TrustOfficer`, `TrustExecutive`, `InvestmentManager`, `TrustOperationsOfficer`, or `TaxSpecialist`, the `X-User-ID` header is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `opened_by_user_id` on a DistributionRequest, `disclosed_by_user_id` on a FeeAssessment, or `initiated_by_user_id` on a TerminationCase — but it never compares such an identifier to any entity's `id`.

Two roles are entity-backed. When `X-User-Role` is `CommitteeMember`, `X-User-ID` is the `id` of the acting CommitteeMember; the server records that id as `committee_member_id` on each vote cast, and a member whose record is no longer ACTIVE may not vote. When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting Beneficiary; ownership checks on any resource that references a Beneficiary compare the resource's beneficiary reference to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_OWN_RESOURCE`.

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

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, and any value outside the inclusive range of 1 to 100 is rejected with `ERR_VALIDATION`. The `offset` parameter controls how many items are skipped and defaults to 0. Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries exactly the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, a `created_at` timestamp recording when the resource was created, an `updated_at` timestamp refreshed on every mutation, and a `version` integer that increments by one on every mutation. Both timestamps are ISO 8601 strings in UTC with three fractional digits. Two resources are deliberately leaner: a CommitteeVote and a LedgerEntry each carry only `id` and `created_at` — `updated_at` and `version` are absent from both, because votes and ledger rows are immutable once written.

The TrustAccount's `version` deserves emphasis because it is the concurrency pivot for the whole API. Any mutation of the trust — including recomputation of its derived fields `income_balance_cents`, `principal_balance_cents`, `reserved_income_cents`, `reserved_principal_cents`, `available_income_cents`, `available_principal_cents`, `total_market_value_cents`, or `pending_distribution_count` — updates `updated_at` and increments `version` by one. A workflow that touches the trust several times conceptually (for example, terminating a trust, which cancels requests and releases their reservations) increments the version once per the transition's declared side effects, as narrated in Section 3.

### 2.5. Integer-Cent Accounting and Rounding Discipline

All monetary quantities are integers denominated in cents — there are no floating-point dollar amounts anywhere in the API. Where a rule requires rounding, the method is always round half up, applied at the exact step the rule names and never earlier. Percentage weights displayed to users (notably `measured_weight_pct` on a ComplianceReview) are stored as numbers rounded half up to two decimal places, but every breach decision uses the unrounded ratio. Share entitlements are expressed in basis points: `share_bps` is an integer between 1 and 10000 inclusive, and the ACTIVE members of a beneficiary class must sum to exactly 10000 basis points — one hundred percent of the class — at the moments the specification requires it.

### 2.6. The Append-Only Ledger and Derived Fiduciary Balances

Every movement of value into or out of a trust is recorded as a LedgerEntry. The ledger is append-only: an attempt to modify or remove an existing row is always rejected with `ERR_LEDGER_IMMUTABLE`. Each row carries an `amount_cents` that is signed — receipts are positive, while disbursements, fees, and distributions are negative — and a `bucket` of either `INCOME` or `PRINCIPAL`, reflecting the fiduciary requirement to account for income and principal separately.

The trust's balances are never stored inputs; they are derivations. `income_balance_cents` is the sum of `amount_cents` over all of the trust's ledger rows in the INCOME bucket, and `principal_balance_cents` is the same sum over the PRINCIPAL bucket; both default to zero when no rows exist. `reserved_income_cents` and `reserved_principal_cents` accumulate the portions earmarked by distribution requests that are in VOTING or APPROVED, and `available_income_cents` and `available_principal_cents` are each the corresponding balance minus the corresponding reservation. `total_market_value_cents` is the sum of every holding's `market_value_cents` plus both cash balances. All of these derivations are recomputed immediately and synchronously on every contributing mutation — a ledger append, a reservation or release, a purchase, a sale, or a price update.

Because annual statements are computed from the ledger, a later ledger append can falsify a statement that has already been drafted. The staleness rule is global: whenever any workflow appends a LedgerEntry, every AnnualStatement of the same trust in DRAFT or FINALIZED whose `fiscal_year` window contains the new entry's `value_date` automatically transitions to SUPERSEDED. Statements already DELIVERED, ACKNOWLEDGED, or DISPUTED are not touched by this rule.

### 2.7. Optimistic Concurrency Control on Trust Accounts

Two write operations are guarded by optimistic concurrency against the trust's `version`, and both name the same input field. Creating a distribution request (`POST /trusts/distribution-requests`) requires the request body to carry `expected_trust_account_version`, holding the trust `version` the client last observed; if another writer has advanced the trust's version since that observation — for example, a prior request creation or any balance-affecting cascade that moved `pending_distribution_count` or the available balances — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of available funds is stale. Purchasing an investment holding (`POST /trusts/investment-holdings`) works identically: the body must carry `expected_trust_account_version` matching the trust's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since a prior purchase legitimately debited principal cash and advanced the version. No other endpoint takes a version field.

### 2.8. Validation Order and Error Precedence

When several rejection reasons apply to one request, the server evaluates checks in a fixed order so the surfaced error is deterministic. The order is:

1. **Authentication** — the headers `X-User-Role` and `X-User-ID` are present and the role is one of the seven declared roles; otherwise `ERR_UNAUTHENTICATED`.
2. **Request shape** — required fields are present, enum values are valid, integer cent amounts and units are positive where required, date strings are valid, `effective_from` is strictly earlier than `effective_to`, `share_bps` lies between 1 and 10000 inclusive, `limit` lies within its 1 to 100 range, and a TrustDocument's `version_number` is unique within its trust; any violation yields `ERR_VALIDATION`.
3. **Role authorization** — the authenticated role appears in the endpoint's role list; otherwise `ERR_FORBIDDEN`.
4. **Identity, ownership, and segregation of duties** — a Beneficiary acts only on their own requests and their own trust's statements and fee assessments (`ERR_NOT_OWN_RESOURCE`); the controlled steps described in §2.9 require two different users (`ERR_SEGREGATION_OF_DUTIES`).
5. **Existence** — path identifiers are validated left to right: a missing trust id yields `ERR_TRUST_NOT_FOUND`, and any other missing path id or body foreign-key id yields `ERR_RESOURCE_NOT_FOUND`.
6. **State validity** — the target entity is in a valid from-state for the requested transition, including terminal-state lockdown (`ERR_INVALID_STATE`); trust-gated child operations require an allowed trust status (`ERR_TRUST_NOT_ACTIVE`); voting requires the request to be in VOTING (`ERR_REQUEST_NOT_VOTING`); disbursement requires APPROVED (`ERR_REQUEST_NOT_APPROVED`); the voting member must be ACTIVE (`ERR_MEMBER_NOT_ACTIVE`); reinstatement requires zero unresolved reviews (`ERR_UNRESOLVED_COMPLIANCE_REVIEWS`); resolving a review requires the drift cured (`ERR_DRIFT_STILL_BREACHED`); and the OCC-guarded writes reject a stale `expected_trust_account_version` (`ERR_STALE_VERSION`).
7. **Fiduciary and compliance gates** — the purpose standard permits the requested `purpose_category` (`ERR_PURPOSE_OUTSIDE_STANDARD`), no purchase lands in a class with an unresolved overweight breach (`ERR_IPS_DRIFT_BREACH`), and the single-holding concentration limit is respected (`ERR_CONCENTRATION_LIMIT_EXCEEDED`).
8. **Temporal and window rules** — IPS windows tile without overlap (`ERR_IPS_PERIOD_OVERLAP`), FINAL fee periods are gap-free (`ERR_FEE_PERIOD_NOT_CONTIGUOUS`), one live statement per fiscal year (`ERR_STATEMENT_YEAR_EXISTS`), one filing per tax year (`ERR_DUPLICATE_TAX_YEAR`), objection windows honored (`ERR_OBJECTION_WINDOW_EXPIRED`), and the 65-day election within its cap (`ERR_INVALID_ELECTION_AMOUNT`).
9. **Cross-entity references** — body references belong to the same trust (`ERR_CROSS_TRUST_REFERENCE`), the beneficiary is ACTIVE (`ERR_BENEFICIARY_NOT_ACTIVE`), and acceptance requires an APPROVED instrument (`ERR_DOCUMENT_NOT_APPROVED`).
10. **Aggregate and uniqueness constraints** — class shares sum to exactly 10000 basis points at acceptance (`ERR_SHARE_SUM_INVALID`), one vote per member per request (`ERR_DUPLICATE_VOTE`), the ledger is immutable (`ERR_LEDGER_IMMUTABLE`), quorum exists (`ERR_COMMITTEE_QUORUM_UNAVAILABLE`), tax clearance requires all filings accepted (`ERR_UNFILED_TAX_RETURNS`), and preparation requires all overlapping FINAL fees posted (`ERR_UNPOSTED_FEE_ASSESSMENTS`).
11. **Funds checks last** — reservation waterfalls, termination reserves, and fee portions are validated against available balances only after every check above has passed (`ERR_INSUFFICIENT_AVAILABLE_BALANCE`, `ERR_FEE_EXCEEDS_AVAILABLE_BALANCE`).

The practical consequence is that a request failing, say, both authentication and a funds check always surfaces `ERR_UNAUTHENTICATED`, and a stale version always surfaces before an insufficient-balance rejection.

### 2.9. Segregation of Duties and Beneficiary Objection Windows

Three controlled steps must be performed by two different people. The operator who discloses a trustee fee may not post that same fee; the TaxSpecialist who prepares a filing may not approve its review; and the operator who initiates a trust termination may not approve its final accounting. Each pairing is enforced by comparing `X-User-ID` against the recorded first-half actor — `disclosed_by_user_id`, `prepared_by_user_id`, and `initiated_by_user_id` respectively — and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`.

Two beneficiary objection windows run for thirty days, measured against the logical clock and inclusive of the thirtieth day. A beneficiary may dispute a disclosed fee while the clock is no later than thirty days after `disclosed_at`, and may dispute a delivered annual statement while the clock is no later than thirty days after `delivered_at`. A dispute arriving after the window closes is rejected with `ERR_OBJECTION_WINDOW_EXPIRED`.

### 2.10. Resource Addressing and the Logical Clock

Paths that name several resources are validated left to right, and the first missing identifier determines the error, as enumerated in §2.8. Most resources in this API are addressed flatly by their own `id`; the trust-scoped action paths under a trust id validate the trust first, so an operation on a nonexistent trust fails with `ERR_TRUST_NOT_FOUND` before any child lookup occurs.

Time inside the system is logical, not wall-clock. Before any call to the clock-setting capability, the server's logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `TrustExecutive` may advance the logical clock to a supplied `to_iso8601` instant; the capability responds with the resulting `current_utc`. Every timestamp the server assigns — `accepted_at`, `submitted_at`, `approved_at`, `decision_at`, `disbursed_at`, `disclosed_at`, `delivered_at`, `acknowledged_at`, `filed_at`, `accepted_at` on filings, `resolved_at`, `distributed_at`, and the `value_date` defaults described in Section 3 — is read from this logical clock.

## 3. Business Logic & Workflows

### 3.1. Opening the Relationship: Trust Setup, Document Interpretation, and Acceptance

A relationship begins when a `TrustOfficer` opens a trust account, supplying its legal `trust_name`, a `trust_type` of `REVOCABLE`, `IRREVOCABLE`, `TESTAMENTARY`, or `CHARITABLE`, the `grantor_name`, the two-letter `governing_state` code of the governing law, the trust's `ein` in the XX-XXXXXXX format, the `fiscal_year_end_month` as an integer from 1 to 12 — where 12 means the trust follows the calendar tax year from January 1 through December 31 — and the `distribution_standard` that will govern permissible distribution purposes: `HEMS`, `SUPPORT`, or `DISCRETIONARY`. The new account starts in DRAFT, reported through its `status` field — every resource in this API carries such a `status` enumeration, and the narratives below give each one's values.

Before the bank will accept the trusteeship, the governing instrument must be on file and approved. A `TrustOfficer` creates a TrustDocument against a `trust_id` with a `version_number` that must be unique within that trust (a duplicate is rejected with `ERR_VALIDATION`), optionally chaining it to a `prior_document_id` — null for the first version — and optionally attaching a free-text `summary`. The document moves DRAFT → SUBMITTED when the officer submits it, which stamps `submitted_at`; submission is only accepted while the owning trust is in DRAFT, UNDER_ACCEPTANCE_REVIEW, or ACTIVE, and is otherwise rejected with `ERR_TRUST_NOT_ACTIVE`. The same officer then records their reading of the dispositive provisions, moving the document SUBMITTED → INTERPRETED by supplying `per_stirpes` — true when a deceased beneficiary's share passes to descendants, false when it lapses pro rata to the surviving class members — together with `interpretation_notes`. A `TrustExecutive` then either approves the interpretation, moving INTERPRETED → APPROVED and stamping `approved_at`, or rejects it, moving INTERPRETED → REJECTED with a recorded `rejected_reason`. Approval carries a cascade: any other TrustDocument of the same trust currently APPROVED automatically becomes SUPERSEDED, so at most one approved instrument governs a trust at any time.

With an approved instrument in hand, the officer moves the trust DRAFT → UNDER_ACCEPTANCE_REVIEW by submitting it for acceptance, and a `TrustExecutive` makes the decision. Acceptance — the transition to ACTIVE — enforces two preconditions in prose order: at least one TrustDocument of the trust must be APPROVED, otherwise `ERR_DOCUMENT_NOT_APPROVED`; and for every `beneficiary_class` that has at least one ACTIVE Beneficiary, the `share_bps` values of that class's ACTIVE members must sum to exactly 10000, otherwise `ERR_SHARE_SUM_INVALID`. A successful acceptance stamps `accepted_at` — null at every other time — and increments the trust's `version`. Declining moves the trust to the terminal ACCEPTANCE_DECLINED with a recorded `reason`.

An ACTIVE trust can be suspended by a `TrustExecutive` (the request takes a `reason`), moving ACTIVE → SUSPENDED. Suspension is protective, not destructive: it does not cancel any non-terminal distribution request, but it blocks opening votes, disbursement, and ledger posting, and it is also imposed automatically the moment a CRITICAL compliance review is created (see §3.4). Investment trading is deliberately exempt — purchases, sales, and price updates remain possible while SUSPENDED so a manager can trade out of the very breach that caused the suspension. Reinstatement from SUSPENDED → ACTIVE is permitted only when the trust has zero ComplianceReviews in OPEN, REMEDIATION_PLANNED, or ESCALATED; otherwise the attempt is rejected with `ERR_UNRESOLVED_COMPLIANCE_REVIEWS`. Termination is covered in §3.9. Across all of these transitions — submit, accept, decline, suspend, reinstate, terminate — each one increments the trust's `version` by one.

### 3.2. Beneficiaries, Share Classes, and the Trust Committee

A `TrustOfficer` enrolls beneficiaries while the trust is in DRAFT, UNDER_ACCEPTANCE_REVIEW, or ACTIVE, supplying the owning `trust_id`, the beneficiary's `full_name`, a `beneficiary_class` of `INCOME` or `REMAINDER`, the `share_bps` entitlement in basis points, and the `date_of_birth` as an ISO date. A beneficiary starts ACTIVE. When a beneficiary dies, the officer records the death with a `deceased_at` date, moving ACTIVE → DECEASED, and three cascades follow. First, every distribution request of that beneficiary in SUBMITTED, UNDER_REVIEW, INFORMATION_REQUESTED, VOTING, or APPROVED is cancelled with `cancelled_reason` set to BENEFICIARY_DECEASED. Second, each such cancellation releases its income and principal reservation on the trust, recomputing `reserved_income_cents` and `reserved_principal_cents` and therefore the available balances. Third, if the trust's APPROVED instrument recorded `per_stirpes` as false, share reallocation runs over the deceased's class; if `per_stirpes` is true, the shares are left unchanged because the deceased's share passes to their descendants.

Reallocation is a largest-remainder apportionment in integer basis points. Let the deceased's share be the basis points they held, and let the survivors be the remaining ACTIVE beneficiaries of the same class. Each survivor's raw increment is the deceased's share multiplied by that survivor's own `share_bps` and divided by the sum of all survivors' shares. Each survivor first receives the floor of that raw increment. The leftover — the deceased's share minus the sum of the floors — is then distributed one basis point at a time to the survivors with the largest fractional remainders, with ties broken by beneficiary `created_at` ascending, never by id. The deceased's share is absorbed in full by the survivors, so the class invariant holds both before and after: the ACTIVE members' shares sum to exactly 10000 basis points.

The bank-level trust committee supplies the votes on discretionary distributions. A `TrustExecutive` creates a CommitteeMember with a `full_name` and a service window from `term_start` to `term_end`; members start ACTIVE. Deactivation moves ACTIVE → INACTIVE and is deliberately non-retroactive: votes the member has already cast remain counted, and the size snapshot taken when voting opened is not recomputed, but the member can no longer cast new votes — an attempt by an INACTIVE member is rejected with `ERR_MEMBER_NOT_ACTIVE`.

### 3.3. Discretionary Distributions: Request, Review, Voting, and Disbursement

A discretionary distribution starts as a DistributionRequest created against a `trust_id` for a `beneficiary_id`, carrying the requested gross `amount_cents` (which must be greater than zero), an `allocation_source` of `INCOME_ONLY`, `PRINCIPAL_ONLY`, `INCOME_FIRST`, or `PRINCIPAL_FIRST`, a `purpose_category` of `HEALTH`, `EDUCATION`, `MAINTENANCE`, `SUPPORT`, `TRAVEL`, `LUXURY`, or `OTHER`, and an optional free-text `purpose_note`. A caller acting as `Beneficiary` may file only for themselves — `X-User-ID` must equal the payload's `beneficiary_id`, otherwise `ERR_NOT_OWN_RESOURCE` — while a `TrustOfficer` may file on a beneficiary's behalf. The beneficiary named must belong to the same trust as the request; a cross-trust reference is rejected with `ERR_CROSS_TRUST_REFERENCE`. The trust must be ACTIVE, otherwise `ERR_TRUST_NOT_ACTIVE`, and the create is OCC-guarded per §2.7, so the body must carry `expected_trust_account_version`. A successful create lands in SUBMITTED, increments the trust's `pending_distribution_count` by one, and increments the trust's `version` by one. The request's `income_portion_cents` and `principal_portion_cents` remain zero until voting opens, and its `approve_count`, `decline_count`, and `abstain_count` tallies track the committee's ballot.

Review is officer-driven. A `TrustOfficer` moves SUBMITTED → UNDER_REVIEW by starting review, and may bounce the request UNDER_REVIEW → INFORMATION_REQUESTED with an `info_request_note`. Only the requesting beneficiary answers: the transition INFORMATION_REQUESTED → UNDER_REVIEW requires `X-User-ID` to equal the request's `beneficiary_id` (`ERR_NOT_OWN_RESOURCE`) and carries the beneficiary's `info_response_note`. This UNDER_REVIEW → INFORMATION_REQUESTED → UNDER_REVIEW loop is unbounded. The beneficiary may also abandon the request: withdrawal moves SUBMITTED, UNDER_REVIEW, or INFORMATION_REQUESTED → WITHDRAWN, is restricted to the owning beneficiary in the same way, decrements `pending_distribution_count` by one, and increments the trust's `version`. An officer's cancellation, carrying a `cancelled_reason`, moves any non-terminal state — SUBMITTED, UNDER_REVIEW, INFORMATION_REQUESTED, VOTING, or APPROVED — to CANCELLED, releasing the reservation if one exists (as described below), decrementing `pending_distribution_count`, and incrementing the trust's `version`.

Opening the vote is the fiduciary hinge, and its preconditions are evaluated in the order given here. The trust must be ACTIVE, otherwise `ERR_TRUST_NOT_ACTIVE`. The beneficiary must be ACTIVE, otherwise `ERR_BENEFICIARY_NOT_ACTIVE`. The `purpose_category` must be permitted by the trust's `distribution_standard`: HEMS permits HEALTH, EDUCATION, MAINTENANCE, and SUPPORT; SUPPORT permits HEALTH, MAINTENANCE, and SUPPORT; DISCRETIONARY permits every category; any other pairing is rejected with `ERR_PURPOSE_OUTSIDE_STANDARD`. At least three CommitteeMembers must be ACTIVE, otherwise `ERR_COMMITTEE_QUORUM_UNAVAILABLE`. Finally the reservation waterfall for the chosen `allocation_source` must succeed against the trust's available balances, otherwise `ERR_INSUFFICIENT_AVAILABLE_BALANCE`: INCOME_ONLY reserves the entire amount from income and requires the amount to be no more than `available_income_cents`; PRINCIPAL_ONLY reserves it entirely from principal against `available_principal_cents`; INCOME_FIRST reserves the lesser of the amount and the available income from income, then the remainder from principal, requiring that remainder to fit within the available principal; PRINCIPAL_FIRST mirrors this, reserving the lesser of the amount and the available principal first and the remainder from income.

A successful opening sets `income_portion_cents` and `principal_portion_cents` per the waterfall, adds them to the trust's `reserved_income_cents` and `reserved_principal_cents`, recomputes the available balances, increments the trust's `version`, snapshots `committee_size_snapshot` as the count of ACTIVE members at that instant, zeroes all three tallies, and records the officer as `opened_by_user_id`. The request is then VOTING.

CommitteeMembers cast ballots by supplying the `vote` field — one of `APPROVE`, `DECLINE`, or `ABSTAIN`. Each ballot appends a CommitteeVote naming the `distribution_request_id`, with `committee_member_id` taken from the caster's `X-User-ID`; the request must be VOTING (`ERR_REQUEST_NOT_VOTING`), the member ACTIVE (`ERR_MEMBER_NOT_ACTIVE`), and one member gets one vote per request — a repeat is rejected with `ERR_DUPLICATE_VOTE`. The quorum threshold is three. After the just-cast vote is appended and the tallies recomputed: if `approve_count` has reached at least three, the request becomes APPROVED — exactly three approvals approves — and the reservation remains in place; otherwise, if `decline_count` has reached at least three, the request becomes DECLINED; otherwise, if the total votes cast now equal `committee_size_snapshot` and `approve_count` is still below three, the request is DECLINED as a full ballot without quorum. Either decision stamps `decision_at` and advances the trust's `version` by one; a decline additionally releases the reservation — the trust's reserved balances are reduced by this request's portions, the available balances recomputed — and decrements `pending_distribution_count`. Because the snapshot is not recomputed after deactivations, votes of a member deactivated mid-ballot still count.

Only an APPROVED request can be paid out. Disbursement by a `TrustOperationsOfficer` requires the request to be APPROVED (`ERR_REQUEST_NOT_APPROVED`) and the trust ACTIVE (`ERR_TRUST_NOT_ACTIVE`). On success, three cascades run. First, the ledger is appended: one DISTRIBUTION row in the INCOME bucket for the negative of `income_portion_cents` when that portion is greater than zero, and one DISTRIBUTION row in the PRINCIPAL bucket for the negative of `principal_portion_cents` when that is greater than zero, each with `value_date` set to the current clock date and `source_entity_type` of DISTRIBUTION_REQUEST pointing back at the request via `source_entity_id`. Second, the trust's balances are recomputed from the ledger, this request's reservation is released, `pending_distribution_count` decrements, and the trust's `version` increments. Third, every AnnualStatement of the trust still in DRAFT or FINALIZED whose `fiscal_year` contains the disbursement's `value_date` is automatically SUPERSEDED, since its totals are now stale. The request lands DISBURSED with `disbursed_at` stamped.

### 3.4. Investment Policy, Trading, and Drift Compliance

Every trust invests against an InvestmentPolicyStatement. An `InvestmentManager` drafts one for a `trust_id` with a half-open effective window from `effective_from` (inclusive) to `effective_to` (exclusive), target and tolerance pairs `equity_target_pct` with `equity_band_pct` and `fixed_income_target_pct` with `fixed_income_band_pct`, and the `alternatives_allowed` flag recording whether ALTERNATIVE-class holdings are permitted under the policy. Creation requires the trust to be in DRAFT, UNDER_ACCEPTANCE_REVIEW, ACTIVE, or SUSPENDED, and the statement starts in DRAFT. Activation moves DRAFT → ACTIVE and enforces window hygiene: the half-open window must not overlap any other statement of the same trust in DRAFT or ACTIVE, though abutting windows — where one statement's `effective_to` equals the other's `effective_from` — are permitted; an overlap is rejected with `ERR_IPS_PERIOD_OVERLAP`. Activation also requires the trust to be ACTIVE or SUSPENDED (`ERR_TRUST_NOT_ACTIVE`). On activation the trust's previously ACTIVE statement, if any, automatically becomes SUPERSEDED, `activated_at` is stamped, and an immediate drift check runs against the new policy, opening a ComplianceReview for each breaching class.

Holdings are positions in a single security. A purchase names the `trust_id`, an `asset_class` of `EQUITY`, `FIXED_INCOME`, `CASH_EQUIVALENT`, or `ALTERNATIVE`, a `ticker`, a positive whole number of `units`, and the `unit_price_cents` paid, plus the OCC field `expected_trust_account_version` per §2.7. Tickers are unique per trust: buying a ticker the trust already holds merges into the existing row, accumulating `units` and `cost_basis_cents` and setting `unit_price_cents` to the purchase price — and if that row was CLOSED, the purchase reopens it to OPEN. Each purchase appends an INVESTMENT_PURCHASE row in the PRINCIPAL bucket for the negative of units times price, recomputes the trust's balances and `total_market_value_cents`, and increments the trust's `version`. The trust must be ACTIVE or SUSPENDED. A holding's `market_value_cents` is always exactly its `units` multiplied by its `unit_price_cents`, an exact integer product, and `priced_at` records the timestamp associated with the latest price — the creation time, or the `priced_at` supplied with a price update.

Two safety gates constrain every purchase, evaluated per §2.8. Buying into a class is blocked while any ComplianceReview for that class and trust is non-RESOLVED with `direction` OVERWEIGHT — the rejection is `ERR_IPS_DRIFT_BREACH` — whereas buying into an UNDERWEIGHT class is allowed precisely because it is the remediation path. Separately, concentration is capped: if a holding's post-trade market value would be strictly more than twenty-five percent of the trust's `total_market_value_cents`, the purchase is rejected with `ERR_CONCENTRATION_LIMIT_EXCEEDED`; landing exactly at twenty-five percent is permitted.

Sales take a number of `units` and credit the proceeds — units multiplied by the current `unit_price_cents` — to PRINCIPAL via an INVESTMENT_SALE row, reduce `cost_basis_cents` pro rata as the basis multiplied by units sold divided by units held before the sale, rounded half up, and recompute trust balances and market value with the usual version increment. Selling the entire position drives `units` to zero and the holding to CLOSED with `market_value_cents` zero; as noted, a later purchase of the same ticker reopens it. Price updates take a new `unit_price_cents` and its `priced_at`, recompute the holding's market value and the trust's total market value, run the drift check, and increment the trust's `version`.

The drift check compares reality to policy for the two banded classes, EQUITY and FIXED_INCOME. For each class, the raw weight is the summed `market_value_cents` of the trust's holdings in that class divided by the trust's `total_market_value_cents`, carried as an exact unrounded decimal. An overweight breach occurs when the raw weight is strictly greater than the target plus the band — the target and band being percentages converted to fractions of one hundred — and an exact landing on the band edge is not a breach; an underweight breach occurs when the raw weight is strictly less than the target minus the band. The stored `measured_weight_pct` is the raw weight converted to a percentage and rounded half up to two decimals — a display value only, never used for the breach decision — and `band_limit_pct` records the band edge that was breached: target plus band for an overweight, target minus band for an underweight. A breach's `severity` is CRITICAL only when the direction is OVERWEIGHT and the unrounded weight exceeds the target plus twice the band; every other breach is STANDARD. If no review already exists in a non-RESOLVED state for that trust and class, the check opens one, naming the breached `asset_class` and the `investment_policy_statement_id` of the ACTIVE policy; if such a review already exists, the check updates it in place — direction, measured weight, band limit, severity — and never creates a duplicate. The creation of a CRITICAL review immediately suspends the trust, ACTIVE → SUSPENDED. When no ACTIVE policy exists for the trust, or when `total_market_value_cents` is zero, the check is a no-op — the latter being the division-by-zero guard. Beyond the automatic runs at activation and price update, an `InvestmentManager` or `TrustOfficer` may invoke the check on demand against a trust, receiving `opened_review_count` and the `opened_review_ids` of any reviews created.

Reviews are worked to resolution. An `InvestmentManager` records a plan, moving OPEN → REMEDIATION_PLANNED with a `remediation_note`; a `TrustExecutive` may escalate, moving OPEN or REMEDIATION_PLANNED → ESCALATED. Resolution — from OPEN, REMEDIATION_PLANNED, or ESCALATED → RESOLVED — requires the class's current unrounded weight to be back within the band inclusive, meaning no less than the target minus the band and no more than the target plus the band; a premature resolve is rejected with `ERR_DRIFT_STILL_BREACHED`. A successful resolve stamps `resolved_at`.

### 3.5. Cash Receipts and Principal–Income Allocation

Manual ledger posting is the domain of the `TrustOperationsOfficer`, and the trust must be ACTIVE or TERMINATING — recall from §3.1 that suspension blocks ledger posting. A posting names the `trust_id`, an `entry_kind`, a signed `amount_cents`, the `value_date` that fixes the entry's fiscal-year attribution, and an optional free-text `description`. The manual kinds are RECEIPT and ADJUSTMENT; the remaining kinds — DISBURSEMENT, FEE, DISTRIBUTION, TAX_PAYMENT, INVESTMENT_PURCHASE, and INVESTMENT_SALE — are written by system workflows such as disbursement, fee posting, and trading, never by hand. Every row also carries a polymorphic provenance pair: `source_entity_type`, one of DISTRIBUTION_REQUEST, FEE_ASSESSMENT, TAX_RETURN_FILING, TERMINATION_CASE, INVESTMENT_HOLDING, or MANUAL, and `source_entity_id`, the referenced row's id — null whenever the source is MANUAL.

Receipts are classified between the buckets in the UPIA style, and the `bucket` of a RECEIPT row is always derived from its `receipt_type`, never taken from the caller; only ADJUSTMENT rows accept an explicit `bucket` input. A `receipt_type` is required when the `entry_kind` is RECEIPT, and the allocation runs as follows. INITIAL_FUNDING is entirely principal. INTEREST is entirely income. ORDINARY_DIVIDEND is entirely income. RENTAL_INCOME splits ninety percent to income — the income share is the receipt amount multiplied by ninety percent, rounded half up — and the remainder to principal. MINERAL_ROYALTY splits ten percent to income on the same rounded basis, with the remainder to principal. CAPITAL_GAIN_DISTRIBUTION is entirely principal. SALE_PROCEEDS is entirely principal. A fully-classified receipt appends one LedgerEntry; a split receipt appends two, the INCOME row first and the PRINCIPAL row second, and any rounding remainder always lands in PRINCIPAL.

Posting recomputes the trust's balances and total market value, increments the trust's `version`, and — per the staleness rule of §2.6 — supersedes any DRAFT or FINALIZED annual statement whose fiscal year contains the entry's `value_date`.

### 3.6. Trustee Fees: Assessment, Disclosure, Posting, and Reversal

Trustee compensation is assessed quarterly through a FeeAssessment created by a `TrustOperationsOfficer` for a `trust_id` over the closed interval from `period_start` to `period_end`, in one of two `variant`s. A PROVISIONAL assessment is an estimate for disclosure and planning: its `base_market_value_cents` is the trust's `total_market_value_cents` at calculation time, at current prices. A FINAL assessment is authoritative for a closed period: each holding is repriced at the latest price observation whose `priced_at` falls on or before the end of `period_end` (the creation price counts as an observation), the base is the sum of those as-of market values plus the currently posted income and principal cash balances, and identical holdings can therefore yield a different fee between the two variants. FINAL periods must tile with no gap and no overlap: the `period_start` of a new FINAL assessment must be exactly one day after the `period_end` of the latest non-REVERSED FINAL assessment for the trust, otherwise `ERR_FEE_PERIOD_NOT_CONTIGUOUS`; PROVISIONAL rows do not participate in the tiling rule. The trust must be ACTIVE or TERMINATING.

The fee itself is tiered on the base. The first tier charges one percent on the portion of the base up to one million dollars — 100,000,000 cents. The second tier charges three-quarters of one percent on the portion above one million dollars, up to a two-million-dollar span. The third tier charges one-half of one percent on any portion above three million dollars. The sum of the three tiers is the `annual_fee_cents`. Dividing the annual fee by four and rounding half up to whole cents gives the quarterly amount; the `assessed_fee_cents` is that quarterly amount floored at a minimum quarterly fee of 125,000 cents — twelve hundred fifty dollars. The charge is then split between the buckets: `income_portion_cents` is the assessed fee multiplied by one half, rounded half up, and `principal_portion_cents` is whatever remains of the assessed fee, so the two portions always sum back to the assessed fee. Every multiplication by a rate uses exact decimal arithmetic, rounding half up only at the named steps. Creation stamps `calculated_by_user_id` from the caller's `X-User-ID` and lands the assessment in CALCULATED.

Disclosure moves CALCULATED → DISCLOSED, recording `disclosed_by_user_id` and stamping `disclosed_at`, which starts the thirty-day objection window of §2.9. Posting moves DISCLOSED → POSTED and is segregation-controlled: the poster's `X-User-ID` must differ from `disclosed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. Posting is also a funds check, evaluated last per §2.8: `income_portion_cents` must fit within the trust's `available_income_cents` and `principal_portion_cents` within `available_principal_cents`, otherwise `ERR_FEE_EXCEEDS_AVAILABLE_BALANCE`. A successful post appends two ledger rows — a FEE row in the INCOME bucket for the negative of the income portion and a FEE row in the PRINCIPAL bucket for the negative of the principal portion, both sourced to FEE_ASSESSMENT — recomputes the trust's balances and available amounts, supersedes stale DRAFT or FINALIZED statements whose fiscal year contains the new entries' `value_date`, increments the trust's `version`, and records `posted_by_user_id`.

A beneficiary of the same trust — ACTIVE, with `X-User-ID` equal to their beneficiary id, otherwise `ERR_NOT_OWN_RESOURCE` — may object while the window is open, moving DISCLOSED → DISPUTED with a `dispute_reason`; a late objection is rejected with `ERR_OBJECTION_WINDOW_EXPIRED`. A dispute sends the assessment back to the drawing board: recalculation moves DISPUTED → CALCULATED, recomputes every computed amount field from current inputs under the tiered rule, and clears the disclosure fields. The DISCLOSED → DISPUTED → CALCULATED loop is unbounded. Finally, a `TrustExecutive` may reverse a POSTED assessment, moving POSTED → REVERSED with a `reason`: offsetting ADJUSTMENT rows are appended — the income portion added back to INCOME and the principal portion added back to PRINCIPAL — so the net effect of posting followed by reversal on every balance is exactly zero, and the trust's `version` increments.

### 3.7. Annual Statements and Beneficiary Objections

Once a year the bank reports to beneficiaries through an AnnualStatement generated by a `TrustOfficer` for a `trust_id` and a `fiscal_year` such as 2026; the trust must be ACTIVE, SUSPENDED, TERMINATING, or TERMINATED. At most one non-SUPERSEDED statement may exist per trust and fiscal year — a duplicate is rejected with `ERR_STATEMENT_YEAR_EXISTS` — and generation computes every total from the ledger, for a calendar fiscal year when `fiscal_year_end_month` is 12.

The statement window runs from January 1 through December 31 of the `fiscal_year`, inclusive. `opening_income_cents` and `opening_principal_cents` are the sums of signed ledger amounts, per bucket, whose `value_date` falls before the window opens. `receipts_income_cents` and `receipts_principal_cents` are the sums of the positive entries, per bucket, inside the window. `disbursements_cents` is the absolute value of the sum of negative entries inside the window whose kind is neither DISTRIBUTION nor FEE. `fees_cents` is the absolute sum of FEE entries in the window, and `distributions_cents` the absolute sum of DISTRIBUTION entries. `closing_income_cents` and `closing_principal_cents` are each the opening figure plus all signed entries of that bucket inside the window. All are integer cents with no rounding.

The statement starts in DRAFT. A `TrustOfficer` finalizes it (DRAFT → FINALIZED) and later delivers it (FINALIZED → DELIVERED), the latter stamping `delivered_at` and opening the thirty-day objection window. A beneficiary of the trust — again `X-User-ID` must be an ACTIVE Beneficiary of the same trust, otherwise `ERR_NOT_OWN_RESOURCE` — either acknowledges the statement, DELIVERED → ACKNOWLEDGED with `acknowledged_at` stamped, or disputes it within the window, DELIVERED → DISPUTED with a `dispute_reason`, a late attempt drawing `ERR_OBJECTION_WINDOW_EXPIRED`. A dispute triggers regeneration: DISPUTED → DRAFT, recomputing all totals from the current ledger and clearing `delivered_at` and `dispute_reason`; the DELIVERED → DISPUTED → DRAFT loop is unbounded. Independently of this workflow, the staleness rule of §2.6 can supersede a DRAFT or FINALIZED statement at any time, moving it to SUPERSEDED when a ledger entry lands inside its fiscal year.

### 3.8. Form 1041 Tax Filings and Amendments

Fiduciary income-tax coordination runs through a TaxReturnFiling opened by a `TaxSpecialist` for a `trust_id` and a `tax_year`; the trust must be ACTIVE, SUSPENDED, TERMINATING, or TERMINATED, and there is exactly one filing per trust and tax year ever — a second open attempt is rejected with `ERR_DUPLICATE_TAX_YEAR`. The filing starts in DATA_COLLECTION with `amendment_number` zero.

While collecting data, the specialist may recompute the tentative distributable net income at any time; the filing stays in DATA_COLLECTION and refreshes `tentative_dni_cents` as a snapshot over the entries posted so far. The authoritative computation happens at preparation time, and both variants follow the same pinned sequence of steps over the ledger rows whose `value_date` falls inside the tax year — January 1 through December 31 when `fiscal_year_end_month` is 12. First, gross income is the sum of the positive INCOME rows in the year, counting RECEIPT rows only and excluding ADJUSTMENT reversals of fees. Second, income expenses are the absolute sum of the FEE rows in the INCOME bucket in the year. Third, distributable net income is gross income minus income expenses. Fourth, amounts paid are the absolute sum of DISTRIBUTION rows in the year. Fifth, the distribution deduction is the lesser of distributable net income and the amounts paid plus any `elected_65day_amount_cents` — the amount of next-year distributions the fiduciary elects into the tax year under the 65-day rule, defaulting to zero. Sixth, the trust's taxable income is the distributable net income minus the distribution deduction minus the complex-trust exemption of 30,000 cents — three hundred dollars — carried on the filing as `exemption_cents`. The tentative variant reads the ledger as posted at tentative-computation time; the final variant recomputes at preparation time, so receipts posted between the two calls change the final figures relative to the tentative ones.

Preparation itself — DATA_COLLECTION → PREPARED — accepts the optional `elected_65day_amount_cents` and enforces two gates. Every FeeAssessment of the trust with variant FINAL, a status other than REVERSED, and a period overlapping the tax year must be POSTED, otherwise `ERR_UNPOSTED_FEE_ASSESSMENTS`. And the elected amount must not exceed the distributions disbursed with a `value_date` between January 1 and March 6 of the following tax year, inclusive, otherwise `ERR_INVALID_ELECTION_AMOUNT`. A successful preparation computes `dni_cents`, `distribution_deduction_cents`, and `trust_taxable_income_cents` per the pinned sequence and records `prepared_by_user_id` from the caller.

Review is segregation-controlled. The preparer submits the filing for review (PREPARED → UNDER_REVIEW), and a different `TaxSpecialist` approves it (UNDER_REVIEW → FILED): the reviewer's `X-User-ID` must differ from `prepared_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`, and approval records `reviewed_by_user_id` and stamps `filed_at`. Acceptance by the taxing authority is then recorded (FILED → ACCEPTED) with `accepted_at` stamped; ACCEPTED is terminal. If the authority instead demands changes, the filing moves FILED → AMENDMENT_REQUIRED with a recorded `reason`, and beginning the amendment returns it to DATA_COLLECTION, increments `amendment_number` by one, and clears both `prepared_by_user_id` and `reviewed_by_user_id` so the segregation pairing starts fresh. The FILED → AMENDMENT_REQUIRED → DATA_COLLECTION loop is unbounded.

### 3.9. Trust Termination and the Final Distribution Waterfall

Termination begins when a `TrustOfficer` or `TrustExecutive` terminates an ACTIVE trust, supplying a `reason`. The trust moves ACTIVE → TERMINATING, and three cascades run in order. Every DistributionRequest of the trust in SUBMITTED, UNDER_REVIEW, INFORMATION_REQUESTED, VOTING, or APPROVED is cancelled with `cancelled_reason` set to TRUST_TERMINATING. Each such cancellation releases its reservation, recomputing `reserved_income_cents` and `reserved_principal_cents` — and therefore the available balances — and driving `pending_distribution_count` to zero. A TerminationCase is then created in INITIATED against the now-released balances, recording the caller as `initiated_by_user_id` and retaining the termination `reason`. The trust's `version` increments.

The case then walks a controlled gauntlet. A `TrustOfficer` reserves liabilities, moving INITIATED → LIABILITIES_RESERVED by recording `reserve_taxes_cents` for final taxes and `reserve_fees_cents` for final trustee fees; the two reserves together must fit within the trust's `available_principal_cents`, otherwise `ERR_INSUFFICIENT_AVAILABLE_BALANCE`. A `TaxSpecialist` records tax clearance, moving LIABILITIES_RESERVED → TAX_CLEARANCE_RECEIVED, which requires every TaxReturnFiling of the trust to be ACCEPTED — any filing short of acceptance yields `ERR_UNFILED_TAX_RETURNS`. A `TrustExecutive` approves the final accounting, moving TAX_CLEARANCE_RECEIVED → FINAL_ACCOUNTING_APPROVED, and this is the third segregation pairing: the approver's `X-User-ID` must differ from `initiated_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`; approval records `approved_by_user_id`.

Distribution executes the final waterfall, run by a `TrustOperationsOfficer` moving FINAL_ACCOUNTING_APPROVED → DISTRIBUTED. The distributable income is the trust's `income_balance_cents` at distribute time, paid to the INCOME class; the distributable principal is `principal_balance_cents` minus `reserve_taxes_cents` minus `reserve_fees_cents`, paid to the REMAINDER class, with the reserves deliberately remaining as principal balance. Payout lines are built over every beneficiary of the class whose `share_bps` is greater than zero at distribute time — ACTIVE members and, where the instrument is per stirpes, the estates of deceased beneficiaries whose shares passed to their descendants (recall from §3.2 that a non-per-stirpes death reallocates the deceased's share to survivors, leaving nothing to pay). Each line's amount is the class pool multiplied by the beneficiary's `share_bps` and divided by 10000, rounded half up to whole cents — the per-line rounding happens first. The delta between the pool and the sum of the rounded lines, which may be negative, is then applied to the line of the beneficiary with the largest `share_bps` in that class, ties broken by beneficiary `created_at` ascending, never by id. The resulting `distribution_lines` are ordered with all INCOME-class lines first, then all REMAINDER-class lines, each class internally ordered by beneficiary `created_at` ascending. The waterfall records `distributable_income_cents` and `distributable_principal_cents` on the case, appends one DISTRIBUTION ledger row per line — income-class lines to the INCOME bucket, remainder-class lines to the PRINCIPAL bucket — recomputes the trust's balances, transitions the trust TERMINATING → TERMINATED with a version increment, and stamps `distributed_at`.

Closing the file is the last act. A `TrustOfficer` moves DISTRIBUTED → CLOSED only when two conditions hold: the AnnualStatement of the trust for the `fiscal_year` containing `distributed_at` is ACKNOWLEDGED, otherwise `ERR_FINAL_STATEMENT_NOT_ACKNOWLEDGED`; and the TaxReturnFiling of the trust for the `tax_year` containing `distributed_at` is ACCEPTED, otherwise `ERR_UNFILED_TAX_RETURNS`. Closing transitions the trust TERMINATED → CLOSED — terminal — and increments its `version` one final time.

## 4. Endpoint Definitions

Operations that create a new resource — a trust, document, beneficiary, committee member, distribution request, vote, policy statement, holding, ledger posting, fee assessment, annual statement, or tax filing — return `201 Created`. Operations that transition or modify an existing resource return `200 OK`. The ledger's modification route is the deliberate exception: it never succeeds, because the ledger is append-only (see §2.6).

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | TrustExecutive |
| POST | `/trusts` | Create a trust account in DRAFT | TrustOfficer |
| GET | `/trusts` | List trust accounts | TrustOfficer, TrustExecutive, InvestmentManager, TrustOperationsOfficer, TaxSpecialist |
| GET | `/trusts/{id}` | Read a trust account | TrustOfficer, TrustExecutive, InvestmentManager, TrustOperationsOfficer, TaxSpecialist |
| POST | `/trusts/{id}/submit-for-acceptance` | Move DRAFT to UNDER_ACCEPTANCE_REVIEW | TrustOfficer |
| POST | `/trusts/{id}/accept` | Accept the trusteeship; move UNDER_ACCEPTANCE_REVIEW to ACTIVE | TrustExecutive |
| POST | `/trusts/{id}/decline-acceptance` | Move UNDER_ACCEPTANCE_REVIEW to ACCEPTANCE_DECLINED | TrustExecutive |
| POST | `/trusts/{id}/suspend` | Move ACTIVE to SUSPENDED | TrustExecutive |
| POST | `/trusts/{id}/reinstate` | Move SUSPENDED to ACTIVE | TrustExecutive |
| POST | `/trusts/{id}/terminate` | Move ACTIVE to TERMINATING; opens a TerminationCase | TrustOfficer, TrustExecutive |
| POST | `/trusts/documents` | Create a trust document in DRAFT | TrustOfficer |
| GET | `/trusts/documents` | List trust documents | TrustOfficer, TrustExecutive, InvestmentManager, TrustOperationsOfficer, TaxSpecialist |
| GET | `/trusts/documents/{id}` | Read a trust document | TrustOfficer, TrustExecutive, InvestmentManager, TrustOperationsOfficer, TaxSpecialist |
| POST | `/trusts/documents/{id}/submit` | Move DRAFT to SUBMITTED | TrustOfficer |
| POST | `/trusts/documents/{id}/interpret` | Move SUBMITTED to INTERPRETED; records the interpretation | TrustOfficer |
| POST | `/trusts/documents/{id}/approve` | Move INTERPRETED to APPROVED; supersedes the prior approved document | TrustExecutive |
| POST | `/trusts/documents/{id}/reject-interpretation` | Move INTERPRETED to REJECTED | TrustExecutive |
| POST | `/trusts/beneficiaries` | Add a beneficiary to a trust | TrustOfficer |
| GET | `/trusts/beneficiaries` | List beneficiaries | TrustOfficer, TrustExecutive, InvestmentManager, TrustOperationsOfficer, TaxSpecialist |
| GET | `/trusts/beneficiaries/{id}` | Read a beneficiary | TrustOfficer, TrustExecutive, InvestmentManager, TrustOperationsOfficer, TaxSpecialist |
| POST | `/trusts/beneficiaries/{id}/mark-deceased` | Move ACTIVE to DECEASED; cancels the beneficiary's open requests and may reallocate shares | TrustOfficer |
| POST | `/trusts/committee-members` | Create a committee member in ACTIVE | TrustExecutive |
| GET | `/trusts/committee-members` | List committee members | TrustOfficer, TrustExecutive, InvestmentManager, TrustOperationsOfficer, TaxSpecialist, CommitteeMember |
| GET | `/trusts/committee-members/{id}` | Read a committee member | TrustOfficer, TrustExecutive, InvestmentManager, TrustOperationsOfficer, TaxSpecialist, CommitteeMember |
| POST | `/trusts/committee-members/{id}/deactivate` | Move ACTIVE to INACTIVE | TrustExecutive |
| POST | `/trusts/distribution-requests` | File a discretionary distribution request in SUBMITTED | Beneficiary, TrustOfficer |
| GET | `/trusts/distribution-requests` | List distribution requests | TrustOfficer, TrustExecutive, TrustOperationsOfficer, CommitteeMember |
| GET | `/trusts/distribution-requests/{id}` | Read a distribution request | TrustOfficer, TrustExecutive, TrustOperationsOfficer, CommitteeMember, Beneficiary |
| POST | `/trusts/distribution-requests/{id}/start-review` | Move SUBMITTED to UNDER_REVIEW | TrustOfficer |
| POST | `/trusts/distribution-requests/{id}/request-information` | Move UNDER_REVIEW to INFORMATION_REQUESTED | TrustOfficer |
| POST | `/trusts/distribution-requests/{id}/provide-information` | Move INFORMATION_REQUESTED to UNDER_REVIEW | Beneficiary |
| POST | `/trusts/distribution-requests/{id}/open-voting` | Move UNDER_REVIEW to VOTING; reserves funds and snapshots the committee | TrustOfficer |
| POST | `/trusts/distribution-requests/{id}/vote` | Cast a committee ballot; auto-decides at quorum | CommitteeMember |
| GET | `/trusts/votes` | List committee votes | TrustOfficer, TrustExecutive, CommitteeMember |
| GET | `/trusts/votes/{id}` | Read a committee vote | TrustOfficer, TrustExecutive, CommitteeMember |
| POST | `/trusts/distribution-requests/{id}/disburse` | Move APPROVED to DISBURSED; posts the distribution to the ledger | TrustOperationsOfficer |
| POST | `/trusts/distribution-requests/{id}/withdraw` | Move SUBMITTED, UNDER_REVIEW, or INFORMATION_REQUESTED to WITHDRAWN | Beneficiary |
| POST | `/trusts/distribution-requests/{id}/cancel` | Move any non-terminal state to CANCELLED | TrustOfficer |
| POST | `/trusts/investment-policy-statements` | Create a policy statement in DRAFT | InvestmentManager |
| GET | `/trusts/investment-policy-statements` | List policy statements | TrustOfficer, TrustExecutive, InvestmentManager |
| GET | `/trusts/investment-policy-statements/{id}` | Read a policy statement | TrustOfficer, TrustExecutive, InvestmentManager |
| POST | `/trusts/investment-policy-statements/{id}/activate` | Move DRAFT to ACTIVE; supersedes the prior policy and runs a drift check | InvestmentManager |
| POST | `/trusts/investment-holdings` | Purchase a holding; merges into the same-ticker row | InvestmentManager |
| GET | `/trusts/investment-holdings` | List holdings | TrustOfficer, TrustExecutive, InvestmentManager |
| GET | `/trusts/investment-holdings/{id}` | Read a holding | TrustOfficer, TrustExecutive, InvestmentManager |
| POST | `/trusts/investment-holdings/{id}/update-price` | Update the unit price; reruns the drift check | InvestmentManager |
| POST | `/trusts/investment-holdings/{id}/sell` | Sell units; credits principal; closes the holding at zero units | InvestmentManager |
| POST | `/trusts/{id}/run-compliance-check` | Run the drift check on demand against a trust | InvestmentManager, TrustOfficer |
| GET | `/trusts/compliance-reviews` | List compliance reviews | TrustOfficer, TrustExecutive, InvestmentManager |
| GET | `/trusts/compliance-reviews/{id}` | Read a compliance review | TrustOfficer, TrustExecutive, InvestmentManager |
| POST | `/trusts/compliance-reviews/{id}/plan-remediation` | Move OPEN to REMEDIATION_PLANNED | InvestmentManager |
| POST | `/trusts/compliance-reviews/{id}/resolve` | Move OPEN, REMEDIATION_PLANNED, or ESCALATED to RESOLVED | InvestmentManager |
| POST | `/trusts/compliance-reviews/{id}/escalate` | Move OPEN or REMEDIATION_PLANNED to ESCALATED | TrustExecutive |
| POST | `/trusts/ledger-entries` | Post a manual RECEIPT or ADJUSTMENT | TrustOperationsOfficer |
| GET | `/trusts/ledger-entries` | List ledger entries | TrustOfficer, TrustExecutive, TrustOperationsOfficer, TaxSpecialist |
| GET | `/trusts/ledger-entries/{id}` | Read a ledger entry | TrustOfficer, TrustExecutive, TrustOperationsOfficer, TaxSpecialist |
| PUT | `/trusts/ledger-entries/{id}` | Append-only guard: always rejected with `ERR_LEDGER_IMMUTABLE` | TrustOperationsOfficer |
| POST | `/trusts/fee-assessments` | Calculate a trustee fee for a period | TrustOperationsOfficer |
| GET | `/trusts/fee-assessments` | List fee assessments | TrustOfficer, TrustExecutive, TrustOperationsOfficer |
| GET | `/trusts/fee-assessments/{id}` | Read a fee assessment | TrustOfficer, TrustExecutive, TrustOperationsOfficer, Beneficiary |
| POST | `/trusts/fee-assessments/{id}/disclose` | Move CALCULATED to DISCLOSED; opens the objection window | TrustOperationsOfficer |
| POST | `/trusts/fee-assessments/{id}/post` | Move DISCLOSED to POSTED; appends the fee to both buckets | TrustOperationsOfficer |
| POST | `/trusts/fee-assessments/{id}/dispute` | Move DISCLOSED to DISPUTED within the objection window | Beneficiary |
| POST | `/trusts/fee-assessments/{id}/recalculate` | Move DISPUTED back to CALCULATED with recomputed amounts | TrustOperationsOfficer |
| POST | `/trusts/fee-assessments/{id}/reverse` | Move POSTED to REVERSED; appends offsetting adjustments | TrustExecutive |
| POST | `/trusts/annual-statements` | Generate an annual statement in DRAFT | TrustOfficer |
| GET | `/trusts/annual-statements` | List annual statements | TrustOfficer, TrustExecutive, TrustOperationsOfficer |
| GET | `/trusts/annual-statements/{id}` | Read an annual statement | TrustOfficer, TrustExecutive, TrustOperationsOfficer, Beneficiary |
| POST | `/trusts/annual-statements/{id}/finalize` | Move DRAFT to FINALIZED | TrustOfficer |
| POST | `/trusts/annual-statements/{id}/deliver` | Move FINALIZED to DELIVERED; opens the objection window | TrustOfficer |
| POST | `/trusts/annual-statements/{id}/acknowledge` | Move DELIVERED to ACKNOWLEDGED | Beneficiary |
| POST | `/trusts/annual-statements/{id}/dispute` | Move DELIVERED to DISPUTED within the objection window | Beneficiary |
| POST | `/trusts/annual-statements/{id}/regenerate` | Move DISPUTED back to DRAFT with recomputed totals | TrustOfficer |
| POST | `/trusts/tax-return-filings` | Open a Form 1041 filing in DATA_COLLECTION | TaxSpecialist |
| GET | `/trusts/tax-return-filings` | List tax filings | TrustOfficer, TrustExecutive, TaxSpecialist |
| GET | `/trusts/tax-return-filings/{id}` | Read a tax filing | TrustOfficer, TrustExecutive, TaxSpecialist |
| POST | `/trusts/tax-return-filings/{id}/compute-tentative` | Refresh the tentative distributable net income snapshot | TaxSpecialist |
| POST | `/trusts/tax-return-filings/{id}/prepare` | Move DATA_COLLECTION to PREPARED; computes final tax figures | TaxSpecialist |
| POST | `/trusts/tax-return-filings/{id}/submit-for-review` | Move PREPARED to UNDER_REVIEW | TaxSpecialist |
| POST | `/trusts/tax-return-filings/{id}/approve-review` | Move UNDER_REVIEW to FILED; reviewer must differ from preparer | TaxSpecialist |
| POST | `/trusts/tax-return-filings/{id}/record-acceptance` | Move FILED to ACCEPTED | TaxSpecialist |
| POST | `/trusts/tax-return-filings/{id}/require-amendment` | Move FILED to AMENDMENT_REQUIRED | TaxSpecialist |
| POST | `/trusts/tax-return-filings/{id}/begin-amendment` | Move AMENDMENT_REQUIRED back to DATA_COLLECTION; increments the amendment count | TaxSpecialist |
| GET | `/trusts/termination-cases` | List termination cases | TrustOfficer, TrustExecutive, TrustOperationsOfficer, TaxSpecialist |
| GET | `/trusts/termination-cases/{id}` | Read a termination case | TrustOfficer, TrustExecutive, TrustOperationsOfficer, TaxSpecialist |
| POST | `/trusts/termination-cases/{id}/reserve-liabilities` | Move INITIATED to LIABILITIES_RESERVED | TrustOfficer |
| POST | `/trusts/termination-cases/{id}/record-tax-clearance` | Move LIABILITIES_RESERVED to TAX_CLEARANCE_RECEIVED | TaxSpecialist |
| POST | `/trusts/termination-cases/{id}/approve-final-accounting` | Move TAX_CLEARANCE_RECEIVED to FINAL_ACCOUNTING_APPROVED | TrustExecutive |
| POST | `/trusts/termination-cases/{id}/distribute` | Move FINAL_ACCOUNTING_APPROVED to DISTRIBUTED; runs the final waterfall and terminates the trust | TrustOperationsOfficer |
| POST | `/trusts/termination-cases/{id}/close` | Move DISTRIBUTED to CLOSED; closes the trust | TrustOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_VALIDATION` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_OWN_RESOURCE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_TRUST_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TRUST_NOT_ACTIVE` | 409 |
| `ERR_REQUEST_NOT_VOTING` | 409 |
| `ERR_REQUEST_NOT_APPROVED` | 409 |
| `ERR_MEMBER_NOT_ACTIVE` | 409 |
| `ERR_UNRESOLVED_COMPLIANCE_REVIEWS` | 409 |
| `ERR_DRIFT_STILL_BREACHED` | 409 |
| `ERR_FINAL_STATEMENT_NOT_ACKNOWLEDGED` | 409 |
| `ERR_PURPOSE_OUTSIDE_STANDARD` | 422 |
| `ERR_IPS_DRIFT_BREACH` | 422 |
| `ERR_CONCENTRATION_LIMIT_EXCEEDED` | 422 |
| `ERR_IPS_PERIOD_OVERLAP` | 409 |
| `ERR_FEE_PERIOD_NOT_CONTIGUOUS` | 409 |
| `ERR_STATEMENT_YEAR_EXISTS` | 409 |
| `ERR_DUPLICATE_TAX_YEAR` | 409 |
| `ERR_OBJECTION_WINDOW_EXPIRED` | 422 |
| `ERR_INVALID_ELECTION_AMOUNT` | 422 |
| `ERR_CROSS_TRUST_REFERENCE` | 422 |
| `ERR_BENEFICIARY_NOT_ACTIVE` | 409 |
| `ERR_DOCUMENT_NOT_APPROVED` | 409 |
| `ERR_SHARE_SUM_INVALID` | 422 |
| `ERR_DUPLICATE_VOTE` | 409 |
| `ERR_LEDGER_IMMUTABLE` | 405 |
| `ERR_COMMITTEE_QUORUM_UNAVAILABLE` | 422 |
| `ERR_UNFILED_TAX_RETURNS` | 409 |
| `ERR_UNPOSTED_FEE_ASSESSMENTS` | 409 |
| `ERR_INSUFFICIENT_AVAILABLE_BALANCE` | 422 |
| `ERR_FEE_EXCEEDS_AVAILABLE_BALANCE` | 422 |
| `ERR_STALE_VERSION` | 412 |
