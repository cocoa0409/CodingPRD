# Senior Benefit Card API — Product Requirements Document

## 1. Introduction

A city's senior services office runs a municipal benefit card program that gives qualifying residents aged sixty-five and over discounted purchases at participating local merchants, together with transit and facility fee waivers. The office needs an API that administers the entire program lifecycle: accepting and adjudicating eligibility applications with verified supporting documents, issuing and replacing benefit cards, enrolling merchants and publishing their discount offers, recording card-present purchases with point-of-sale discount computation, detecting and reviewing fraudulent usage, and settling monthly reimbursement claims against a finite annually appropriated program fund. All endpoints described here are mounted under the `/senior-benefits` prefix.

Two concerns shape every rule in this document. First, the program is a compliance environment: eligibility decisions, document reviews, fraud actions, and claim approvals are audited operations constrained by segregation of duties, so that no single operator can both examine and decide the same case. Second, the program administers finite pools of money — an annual fund per fiscal year, per-merchant monthly reimbursement caps, and a per-cardholder monthly discount ceiling — that are competed for across many transactions and must be accounted for to the cent. A logical clock drives every time-based obligation (recertification windows, card expiry, offer retirement), so that program behavior is fully determined by the timestamps the office sets.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` to identify the acting party and `X-User-Role` to declare the operational capacity in which they act. The system recognizes exactly six roles: `Applicant`, `Cardholder`, `EligibilitySpecialist`, `ProgramAdministrator`, `MerchantOperator`, and `FraudAnalyst`. A request with missing or malformed headers, an unrecognized role name, or — for the entity-backed roles described below — an `X-User-ID` that references no existing entity of the backing type is rejected with `ERR_UNAUTHENTICATED`. An authenticated caller whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`.

The roles differ in how `X-User-ID` binds to persisted entities, and the distinction governs every ownership check in the system:

- When `X-User-Role` is `Cardholder`, `X-User-ID` is the `id` of the acting `Cardholder`; ownership checks on any resource that references a cardholder compare that resource's cardholder reference to `X-User-ID`, and a cardholder may read their own record, their applications, their cards, their fee waivers, and their transactions only.
- When `X-User-Role` is `MerchantOperator`, `X-User-ID` is the `id` of the acting `Merchant`; ownership checks on any resource that references a merchant compare that resource's merchant reference to `X-User-ID`, and an operator may act only for their own merchant.
- When `X-User-Role` is `Applicant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; a new applicant has no program record yet by definition.
- When `X-User-Role` is `EligibilitySpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — for example, as `reviewed_by_user_id` on the applications and documents the specialist examines — but does not compare it to any entity's `id`.
- When `X-User-Role` is `ProgramAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, for example as `decided_by_user_id` on applications the administrator decides.
- When `X-User-Role` is `FraudAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it, for example as `flagged_by_user_id` on transactions the analyst flags.

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

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Time-Driven Transitions

Every date- and time-dependent rule in the program evaluates against a server-maintained **logical clock**, never against wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it advances only when a `ProgramAdministrator` invokes the clock-control capability with a `to_iso8601` instant; the capability responds with the resulting `current_utc`. The logical clock never falls back to wall-clock time on its own.

Setting the clock applies every time-based transition that has become due, in dependency order: first the opening of recertification windows (a cardholder moves from `ACTIVE` to `RECERTIFICATION_DUE` once the clock reaches sixty days before their `recertification_due_date`), then lapse (a cardholder still in `RECERTIFICATION_DUE` moves to `LAPSED` once the clock reaches one day past the due date, and the lapse cascades their cards to `EXPIRED`), then card expiry (any card whose `expires_at` the clock has reached becomes `EXPIRED`), and finally offer retirement (any offer whose `valid_until` the clock date has reached becomes `RETIRED`). Several workflows below — recertification, suspension restoration, claim settlement — are only meaningful when read against this clock.

### 2.5. Common Resource Properties

Every primary resource in the system — applications, verification documents, cardholders, cards, merchants, offers, fee waiver grants, usage transactions, reimbursement claims, and program funds — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it is refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments with every modification to the resource and serves as the basis for optimistic concurrency control.

Any mutation of a resource — including system-driven cascade transitions such as a card expiring because its cardholder lapsed — refreshes that resource's `updated_at` and increments its `version`.

### 2.6. Monetary Precision and Rounding

All monetary amounts in the system are integer counts of cents — purchase amounts, discounts, claim amounts, fund balances, caps, and income figures alike — and are represented in API bodies as integers. Wherever a calculation must produce a cent figure from a fractional intermediate (a percentage of a purchase, a percentage of a discount), the result is rounded half-up to a whole cent. Each calculation in §3 states exactly where in its chain of steps the single rounding occurs; that placement is part of the contract, since rounding at different points yields different cents.

### 2.7. Optimistic Concurrency Control

One write operation in the system is guarded by optimistic concurrency control: the card-issuance operation `POST /senior-benefits/cardholders/{id}/cards` requires the request to carry `expected_cardholder_version`, a non-optional field holding the `version` of the cardholder as the client last observed it. If the supplied value does not match the cardholder's current `version` — because some other write has advanced the cardholder's version since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no card is minted. Issuance supersedes the cardholder's currently live card, so a client acting on a stale view of the cardholder could otherwise supersede a card that is no longer the live one; the version gate forces a re-read first. No other endpoint in the API accepts a version field.

### 2.8. Nested Resource Retrieval

Requests that address nested resources are validated strictly left to right along the path. Existence of each path identifier is confirmed in order — the application `id` before the document `docId`, the merchant before its offers or claims, the cardholder before its cards or fee waivers — and the request is rejected immediately with the 404 error corresponding to the first identifier that does not resolve to an existing resource. The not-found family comprises `ERR_APPLICATION_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_CARDHOLDER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`, `ERR_MERCHANT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, and `ERR_FUND_NOT_FOUND`. A document identifier that exists but belongs to a different application therefore surfaces as `ERR_DOCUMENT_NOT_FOUND`, and only after every path identifier has resolved does the system proceed to state, ownership, and business checks.

### 2.9. Ownership Boundaries for Entity-Backed Roles

Because `MerchantOperator` and `Cardholder` are entity-backed roles (§2.1), several endpoints enforce that the caller acts only on their own records. A `MerchantOperator` caller's `X-User-ID` must equal the merchant being acted upon — the `merchant_id` supplied when recording a purchase, the merchant that owns the transaction being voided, the path merchant when publishing an offer, and the path merchant when filing a reimbursement claim; any mismatch is rejected with `ERR_MERCHANT_OWNERSHIP_MISMATCH` (HTTP 403). Symmetrically, a `Cardholder` caller may read a cardholder record, list its applications, cards, or fee waiver grants, and request a card only when the path cardholder identifier equals their own `X-User-ID`; otherwise the request is rejected with `ERR_CARDHOLDER_OWNERSHIP_MISMATCH` (HTTP 403). When a cardholder filters the usage transaction list, the `cardholder_id` filter must likewise name their own record, and a merchant operator filtering the same list must filter by their own `merchant_id`.

### 2.10. Validation Evaluation Order

A single request can violate several rules at once. The server evaluates guards in a pinned order and reports the earliest failing tier, so the error a client observes is deterministic:

1. **Authentication** — header presence, role recognition, and entity-backed identity resolution; failures surface as `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Role authorization** — whether the caller's role is authorized for the endpoint at all; failures surface as `ERR_FORBIDDEN` (HTTP 403).
3. **Path existence** — the left-to-right identifier resolution of §2.8; failures surface as the 404 family.
4. **Resource state** — whether the target resource is in the state the operation requires (an application that can be reviewed, a document not yet reviewed, a card that is `ACTIVE`, a claim still `SUBMITTED`, a merchant still `ACTIVE`); failures surface as the 409 state family.
5. **Ownership** — the entity-backed boundaries of §2.9; failures surface as `ERR_MERCHANT_OWNERSHIP_MISMATCH` or `ERR_CARDHOLDER_OWNERSHIP_MISMATCH` (HTTP 403).
6. **Fraud and segregation safeguards** — the velocity hard limit on purchase recording (HTTP 422) and the segregation-of-duties guards on application approval and flag clearing (HTTP 403).
7. **Temporal window integrity** — offer and waiver window validity (HTTP 400), window overlap conflicts (HTTP 409), and claim period closure (HTTP 422).
8. **Uniqueness, eligibility, and completeness constraints** — duplicate funds, duplicate pending applications or claims, recertification timing, replacement preconditions, age and income gates, and required-document completeness (HTTP 409 or 422 per the specific rule).
9. **Fiscal gates** — offer resolution, fund existence and sufficiency, and merchant monthly caps (HTTP 402 or 422 per the specific rule).

Within a single endpoint, the same ordering applies to that endpoint's guards; §3 notes the pinned sequence wherever an operation concentrates several of them.

## 3. Business Logic & Workflows

### 3.1. Submitting an Application and the Eligibility Gate

Entry into the program begins when an `Applicant` submits a benefit application. The submission names its `kind` — `INITIAL` for a senior joining the program, or `RECERTIFICATION` for an existing member renewing eligibility — along with the `applicant_full_name`, the `date_of_birth` as an ISO calendar date, the `annual_income_cents` declaring annual household income in cents, and the `residency_address`, a street address inside the municipality. A recertification submission must additionally carry the `cardholder_id` of the member being recertified; for an initial application that linkage does not exist yet, and the field is populated by the system only when and if the application is approved. Every new application enters `SUBMITTED` status, with `reviewed_by_user_id`, `info_request_reason`, `denial_reason`, and `decided_by_user_id` all empty until the corresponding workflow events occur.

Two eligibility gates are evaluated at submission, against the logical clock. The age gate computes the applicant's age in whole years between `date_of_birth` and the clock date, incrementing on the birthday itself — a person born on 1961-08-01 is exactly sixty-five on 2026-08-01 — and requires the result to be at least sixty-five; a younger applicant is rejected with `ERR_ELIGIBILITY_AGE_NOT_MET` (HTTP 422). The income gate requires `annual_income_cents` to be at or below the program limit of $24,000 per year; an income that exceeds the limit by even one cent is rejected with `ERR_ELIGIBILITY_INCOME_EXCEEDED` (HTTP 422), while an income exactly at the limit qualifies. Both gates apply identically to `INITIAL` and `RECERTIFICATION` submissions, and malformed payloads — missing fields, wrong types, negative income, an invalid `kind` — are rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any gate runs.

Recertification carries two additional timing rules. A member may hold at most one non-terminal recertification application at a time: if the named cardholder already has a recertification application in `SUBMITTED`, `UNDER_REVIEW`, or `INFO_REQUESTED`, a further submission is rejected with `ERR_DUPLICATE_PENDING_APPLICATION` (HTTP 409). And recertification is accepted only when the member's record is actually due — the linked cardholder must be in `RECERTIFICATION_DUE` or `LAPSED` status, so a submission naming an `ACTIVE` cardholder whose window has not opened is rejected with `ERR_RECERTIFICATION_NOT_DUE` (HTTP 409). The same timing rule is re-verified at approval time, since a member's standing can change while an application awaits decision.

### 3.2. Intake Review and Document Verification

Once submitted, an application waits for an `EligibilitySpecialist` to begin intake review. Starting review moves the application from `SUBMITTED` to `UNDER_REVIEW` and stamps `reviewed_by_user_id` with the specialist's `X-User-ID`; the same action resumes an application that was previously sent back for information, moving it from `INFO_REQUESTED` back to `UNDER_REVIEW` and refreshing `reviewed_by_user_id` to the resuming specialist. Starting review on an application in any other status is rejected with `ERR_APPLICATION_INVALID_STATE` (HTTP 409). When examination reveals a gap, the specialist sends the application back for more information with a payload `reason`; the application moves from `UNDER_REVIEW` to `INFO_REQUESTED` and the reason is recorded in `info_request_reason`. A missing `reason` is rejected with `ERR_INVALID_REQUEST`, and requesting information on an application that is not `UNDER_REVIEW` is rejected with `ERR_APPLICATION_INVALID_STATE`.

Supporting evidence arrives as verification documents attached to the application by the applicant (or, for recertifications, by the cardholder). Each document declares a `document_type` — one of `PROOF_OF_AGE`, `PROOF_OF_INCOME`, or `PROOF_OF_RESIDENCY` — and a free-form `document_reference` such as a license or notice number, and is attached to its application via `application_id`. A new document enters `SUBMITTED` status, with `reviewed_by_user_id` and `rejection_reason` empty. The specialist adjudicates each document with a `decision` of `VERIFIED` or `REJECTED`; a rejection must carry a `rejection_reason` in the payload (its absence is an `ERR_INVALID_REQUEST`), and the decision stamps `reviewed_by_user_id` with the reviewing specialist. Document review is guarded by two state checks evaluated parent-first: the parent application must be in `UNDER_REVIEW` or `INFO_REQUESTED` (otherwise `ERR_APPLICATION_INVALID_STATE`), and the document itself must still be `SUBMITTED`, since a document already `VERIFIED` or `REJECTED` is final and re-review is rejected with `ERR_DOCUMENT_ALREADY_REVIEWED` (HTTP 409).

### 3.3. Approval, Enrollment, and the Annual Recertification Cycle

Decision authority rests with the `ProgramAdministrator`, never with intake staff. Denial is the simpler path: the administrator supplies a `reason` (its absence is an `ERR_INVALID_REQUEST`), the application moves from `UNDER_REVIEW` to `DENIED`, and the record captures `denial_reason` and `decided_by_user_id`. Approval is guarded by four checks evaluated in the pinned order of §2.10 — the application must be `UNDER_REVIEW` (otherwise `ERR_APPLICATION_INVALID_STATE`); the segregation-of-duties guard then requires the approving administrator's `X-User-ID` to differ from the application's `reviewed_by_user_id` and from the `reviewed_by_user_id` of every `VERIFIED` document on the application, so that no one who examined the case can decide it (violations surface as `ERR_SEGREGATION_OF_DUTIES`, HTTP 403); document completeness then requires at least one `VERIFIED` document of each of the three types `PROOF_OF_AGE`, `PROOF_OF_INCOME`, and `PROOF_OF_RESIDENCY` (otherwise `ERR_MISSING_REQUIRED_DOCUMENTS`, HTTP 422); and for a `RECERTIFICATION` application the linked cardholder must stand in `RECERTIFICATION_DUE` or `LAPSED` at decision time (otherwise `ERR_RECERTIFICATION_NOT_DUE`). A decided application is terminal, and `decided_by_user_id` records who decided it.

Approval of an `INITIAL` application enrolls the applicant. The system creates a `Cardholder` record in `ACTIVE` status, copying `full_name`, `date_of_birth`, `annual_income_cents`, and `residency_address` from the approved application, and sets the application's `cardholder_id` to the new record. The member's `recertification_due_date` is set to the approval clock date plus 365 days. In the same act the system mints the member's first benefit card: a server-generated unique sixteen-digit `card_number`, `issue_reason` of `INITIAL`, `status` of `ACTIVE`, `issued_at` set to the clock timestamp, and `expires_at` set two calendar years after issuance. The cardholder record also surfaces derived figures on every read: `age_years`, the whole-year age against the current clock date; `fraud_flag_count`, the number of the member's transactions currently in `FLAGGED` status; `ytd_discount_cents`, the sum of `discount_cents` over the member's transactions in `POSTED` or `FLAGGED` status whose `created_at` falls inside the clock's current calendar year; and `ytd_transaction_count`, the count of that same inclusion set.

Membership is renewed annually. When the clock reaches sixty days before a member's `recertification_due_date`, the member moves automatically from `ACTIVE` to `RECERTIFICATION_DUE`, opening the window in which a recertification application will be accepted. If the window closes without an approval — the clock reaching one day past the due date — the member lapses to `RECERTIFICATION_DUE` → `LAPSED`, and the lapse cascades: every card of the member in `ACTIVE` or `SUSPENDED` status becomes `EXPIRED`, each such card mutation bumping the card's `version` and refreshing its `updated_at`. Approval of a recertification application restores the member from either `RECERTIFICATION_DUE` or `LAPSED` back to `ACTIVE`, pushes `recertification_due_date` to the approval clock date plus 365 days, and refreshes `annual_income_cents` and `residency_address` from the newly approved application. Restoration after a lapse does not resurrect cards: the member's cards were already expired by the lapse cascade and remain `EXPIRED`, so a lapsed-then-recertified member must separately request a renewal card before discounts resume.

Separately from the annual cycle, a `FraudAnalyst` may permanently revoke a membership — for fraud or confirmed ineligibility — supplying a `reason`. Revocation is available from `ACTIVE`, `RECERTIFICATION_DUE`, `SUSPENDED`, or `LAPSED` and moves the member to the terminal `REVOKED` status; from `ACTIVE`, `RECERTIFICATION_DUE`, or `SUSPENDED` it cascades the member's `ACTIVE` or `SUSPENDED` cards to `REVOKED`, while a lapsed member's cards are already `EXPIRED` and nothing further happens to them. Revoking an already `REVOKED` member is rejected with `ERR_CARDHOLDER_ALREADY_TERMINAL` (HTTP 409). A member's application history — initial and recertification filings alike — remains listable through the cardholder's applications collection.

### 3.4. Card Issuance: Replacement and Renewal

Beyond the initial card minted at enrollment, a cardholder (or a `ProgramAdministrator` acting on their behalf) may request a further card by supplying a `reason` of `REPLACEMENT` or `RENEWAL`. Because issuance supersedes the member's currently live card, the request must also carry `expected_cardholder_version` holding the cardholder `version` the client last observed; per §2.7, a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is minted. Issuance requires the member to stand in `ACTIVE` or `RECERTIFICATION_DUE` — a `SUSPENDED`, `LAPSED`, or `REVOKED` member is rejected with `ERR_CARDHOLDER_NOT_ACTIVE` (HTTP 409) — and every successful issuance increments the cardholder's `version` by one.

The two reasons serve disjoint situations, and requesting one when its precondition does not hold is rejected with `ERR_REPLACEMENT_NOT_ALLOWED` (HTTP 409). A `REPLACEMENT` requires the member to currently hold a card in `ACTIVE` or `SUSPENDED` status; issuance supersedes that card, moving it to `REPLACED` — whether it was `ACTIVE` or `SUSPENDED` — and recording the superseded card's identifier in the new card's `replaces_card_id`. A `RENEWAL` applies when the member holds no `ACTIVE` or `SUSPENDED` card at all but does hold at least one `EXPIRED` card; the new card's `replaces_card_id` points to the member's most recently created `EXPIRED` card purely as audit lineage, and any prior `EXPIRED` cards keep their status untouched. In both cases the new card is minted `ACTIVE` with a fresh sixteen-digit `card_number`, `issued_at` at the clock, and `expires_at` two calendar years out. Independently of issuance, any card — `ACTIVE` or `SUSPENDED` — becomes `EXPIRED` once the clock reaches its `expires_at`, and the full replacement lineage of a member's cards remains visible through the card collection in all statuses.

### 3.5. Merchants, Discount Offers, and Fee Waiver Grants

A `ProgramAdministrator` enrolls a participating merchant by supplying the business `name`, the `reimbursement_rate_pct` — the percentage of each granted discount the city will repay, greater than zero and at most one hundred — and the `monthly_reimbursement_cap_cents`, a non-negative ceiling on approved reimbursements per calendar month. A merchant is created `ACTIVE`. Termination, also an administrator action, requires the merchant to be `ACTIVE` (otherwise `ERR_MERCHANT_NOT_ACTIVE`, HTTP 409) and moves the merchant to the terminal `TERMINATED` status with two cascades: every `ACTIVE` offer of the merchant becomes `RETIRED`, and every still-`SUBMITTED` reimbursement claim of the merchant is denied with `denial_reason` recorded as `MERCHANT_TERMINATED`. A terminated merchant can no longer record usage, publish offers, or file claims — each such attempt is rejected with `ERR_MERCHANT_NOT_ACTIVE`.

A merchant's point-of-sale operator publishes discount offers, each created `ACTIVE`. An offer declares its `category` — one of `GROCERY`, `PHARMACY`, `DINING`, `RETAIL`, or `SERVICES` — a `discount_pct` greater than zero and at most one hundred, a positive per-transaction ceiling `max_discount_cents`, and a validity window from `valid_from` (an inclusive calendar date) to `valid_until` (an exclusive calendar date), forming a half-open interval. Two window rules guard creation, both tier seven in §2.10: `valid_from` must be strictly earlier than `valid_until` (otherwise `ERR_OFFER_WINDOW_INVALID`, HTTP 400), and the new window must not overlap any existing `ACTIVE` offer of the same merchant and category — overlap under the half-open convention is rejected with `ERR_OFFER_WINDOW_OVERLAP` (HTTP 409), while mere adjacency, one offer's `valid_until` equaling another's `valid_from`, is permitted. Once the clock date reaches an offer's `valid_until`, the offer retires automatically to `RETIRED`. The merchant's offer collection can be listed with optional `status` and `category` filters.

Fee waivers sit alongside merchant discounts. A `ProgramAdministrator` may grant a cardholder a waiver of `waiver_type` `TRANSIT_FARE` or `FACILITY_FEE` over a closed date interval from `start_date` through `end_date`, both inclusive. Granting requires the member to stand in `ACTIVE` or `RECERTIFICATION_DUE` (otherwise `ERR_CARDHOLDER_NOT_ACTIVE`). The interval must be well formed — `start_date` on or before `end_date`, else `ERR_WAIVER_WINDOW_INVALID` (HTTP 400) — and must not overlap any existing grant of the same cardholder and waiver type; because waiver intervals are closed, even touching dates conflict, and an overlap is rejected with `ERR_WAIVER_WINDOW_OVERLAP` (HTTP 409). A member's grants can be listed with an optional `waiver_type` filter.

### 3.6. Recording a Purchase: Offer Resolution, Discounts, and Velocity Control

At the point of sale, a `MerchantOperator` records a purchase by presenting the `card_id` swiped, the `merchant_id` where the sale occurs — which must equal the operator's own merchant, else `ERR_MERCHANT_OWNERSHIP_MISMATCH` — the purchase `category`, and the gross `purchase_amount_cents`, which must be positive. Before any business rule runs, three standing checks fire in a pinned order: the presented card must be `ACTIVE` (a `SUSPENDED`, `REPLACED`, `EXPIRED`, or `REVOKED` card is rejected with `ERR_CARD_NOT_ACTIVE`, HTTP 409); then the cardholder resolved from that card must stand in `ACTIVE` or `RECERTIFICATION_DUE` (otherwise `ERR_CARDHOLDER_NOT_ACTIVE`); then the merchant must be `ACTIVE` (otherwise `ERR_MERCHANT_NOT_ACTIVE`). The system resolves `cardholder_id` from the card and `offer_id` from the merchant's offers, and the new transaction enters `POSTED` status with `flagged_by_user_id`, `flag_reason`, and `voided_by_user_id` empty.

Offer resolution considers the merchant's offers whose category matches the request `category`, whose status is `ACTIVE`, and whose half-open window contains the clock date — `valid_from` on or before the clock date and `valid_until` strictly after it. Because the creation-time overlap rule guarantees at most one such offer per merchant, category, and date, resolution normally yields exactly one candidate; defensively, if several candidates ever exist, the one with the earliest `valid_from` wins, ties broken by earliest `created_at`. If no offer covers the sale, the transaction is rejected with `ERR_NO_ACTIVE_OFFER` (HTTP 422).

The granted discount is computed once at creation and frozen on the transaction as `discount_cents`, immutable thereafter. First, the raw discount is the purchase amount multiplied by the resolved offer's `discount_pct` and divided by one hundred, carried as an exact rational figure with no rounding. Second, the raw figure is capped at the offer's `max_discount_cents`. Third, the member's month-to-date usage is the sum of `discount_cents` across that cardholder's transactions in `POSTED` or `FLAGGED` status whose `created_at` falls inside the clock's current calendar month, and the remaining headroom is the program's monthly discount ceiling of $50 per cardholder minus that usage, floored at zero. Fourth, the granted figure is the lesser of the capped figure and the remaining headroom. Only now is rounding applied: the granted figure is rounded half-up once, to a whole cent, and stored. A cardholder whose month is already exhausted therefore receives a zero-cent discount on further purchases rather than a rejection.

Fraud velocity control runs at creation, before the transaction is persisted, over the cardholder's transactions that are not `VOIDED`, each count including the candidate transaction itself, and the two windows are evaluated in a fixed order. The trailing-window count tallies transactions whose `created_at` falls later than twenty-four hours before the current clock instant and at or before it, and adds one for the candidate; if that total reaches ten, creation is refused outright with `ERR_VELOCITY_HARD_LIMIT` (HTTP 422). Otherwise the calendar-day count tallies transactions whose `created_at` calendar date equals the clock's calendar date and adds one for the candidate; if that total reaches five, the transaction is persisted as `POSTED` and then immediately auto-transitioned to `FLAGGED`, with `flagged_by_user_id` recorded as the literal `SYSTEM` and `flag_reason` recorded as `VELOCITY_AUTO`, and the same fraud cascade described in §3.7 fires from that flag. Because the two windows differ — a burst late yesterday evening counts toward this morning's trailing-window total but not toward today's calendar-day total — the hard limit can refuse a sale even on a quiet calendar day. The transaction list endpoint accepts optional `card_id`, `cardholder_id`, `merchant_id`, `offer_id`, and `status` filters alongside `limit` and `offset`.

### 3.7. Fraud Review: Flagging, Clearing, Voiding, and Standing Restoration

Beyond the automatic velocity flag, a `FraudAnalyst` may manually flag a transaction that stands in `POSTED`, supplying a free-form `reason` (its absence is an `ERR_INVALID_REQUEST`); flagging a transaction in any other status is rejected with `ERR_TRANSACTION_NOT_FLAGGABLE` (HTTP 409). The flag stamps `flagged_by_user_id` with the analyst's `X-User-ID` and `flag_reason` with the supplied reason. Every flag transition — manual or automatic — increments the cardholder's `fraud_flag_count` by one, and when that count reaches three while the member stands in `ACTIVE` or `RECERTIFICATION_DUE`, the system suspends the member: the member's pre-suspension standing is preserved in `pre_suspension_status`, the status becomes `SUSPENDED`, and the suspension cascades the member's `ACTIVE` cards to `SUSPENDED`.

Clearing a flag is deliberately separated from raising it. A `FraudAnalyst` may clear a transaction standing in `FLAGGED` — any other status is rejected with `ERR_TRANSACTION_NOT_FLAGGABLE` — but segregation of duties forbids an analyst from clearing a flag they personally raised: when `flagged_by_user_id` names an analyst rather than `SYSTEM`, a clearer whose `X-User-ID` equals it is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Clearing decrements the member's `fraud_flag_count` by one and empties `flagged_by_user_id` and `flag_reason`, returning the transaction to `POSTED`. When the count thereby drops below three and the member stands `SUSPENDED`, the member is restored to the standing captured in `pre_suspension_status` — `ACTIVE` or `RECERTIFICATION_DUE` — `pre_suspension_status` is emptied, and the restoration cascades the member's `SUSPENDED` cards back to `ACTIVE`.

Voiding is the merchant-side corrective. The `MerchantOperator` of the merchant where the sale occurred — the caller's `X-User-ID` must equal the transaction's `merchant_id`, else `ERR_MERCHANT_OWNERSHIP_MISMATCH` — may void a transaction standing in `POSTED`; voiding is rejected with `ERR_TRANSACTION_NOT_VOIDABLE` (HTTP 409) in any other status, so a `FLAGGED` transaction must first be cleared by a fraud analyst, and `VOIDED` is terminal. The void records `voided_by_user_id` and reverses the member's year-to-date figures, subtracting the transaction's `discount_cents` from `ytd_discount_cents` and decrementing `ytd_transaction_count` by one — equivalently, both figures are recomputed over the member's transactions in `POSTED` or `FLAGGED` status within the clock's current calendar year, from which the voided transaction is now excluded.

### 3.8. Monthly Reimbursement Claims and the Program Fund

The city's side of the ledger begins with the annual appropriation. A `ProgramAdministrator` creates a program fund for a `fiscal_year` with its `allocated_cents` appropriation, which must be positive; one fund exists per fiscal year, and a duplicate is rejected with `ERR_DUPLICATE_FISCAL_YEAR` (HTTP 409). The fund's `paid_cents` is the sum of `final_amount_cents` over approved claims bound to it, and its `available_cents` is the appropriation minus what has been paid; the invariant that `allocated_cents` always equals `available_cents` plus `paid_cents` holds at all times.

After a month closes, a merchant's operator files a reimbursement claim naming the `period_month` in year-month form. The period must be strictly earlier than the clock's current calendar month — a claim for the current or a future month is rejected with `ERR_CLAIM_PERIOD_NOT_CLOSED` (HTTP 422) — and the merchant may hold at most one non-denied claim per period: if a claim for the same merchant and `period_month` stands in `SUBMITTED` or `APPROVED`, refiling is rejected with `ERR_DUPLICATE_PENDING_CLAIM` (HTTP 409), so refiling becomes possible only after every prior claim for that period has been denied. A new claim enters `SUBMITTED` with `program_fund_id` and `final_amount_cents` empty, and its `provisional_amount_cents` is computed and frozen at submission.

Claim amounts, provisional and final alike, are line-item aggregations over the merchant's usage transactions whose `created_at` falls inside the claimed calendar month. Each eligible transaction contributes a line amount: the transaction's `discount_cents` multiplied by the merchant's `reimbursement_rate_pct` and divided by one hundred, rounded half-up to a whole cent. The claim amount is the sum of those per-line rounded amounts — rounding strictly precedes summation, each line being rounded first and only the rounded line amounts added; summing unrounded contributions and rounding once at the end is a different rule and is not how the program computes claims. The two bases differ only in which transactions are eligible: the provisional basis, used at submission, includes transactions standing in `POSTED` or `FLAGGED` as they stand at the submission clock, while the final basis, used at approval, includes only transactions standing in `POSTED` at the approval clock — transactions still `FLAGGED` and unresolved are excluded, as are `VOIDED` ones. A flag or void between filing and approval therefore lowers the final settlement below the provisional figure.

Approval is the administrator's settlement act, guarded in the order of §2.10. The claim must stand in `SUBMITTED`, else `ERR_CLAIM_NOT_SUBMITTED` (HTTP 409). A program fund must exist whose `fiscal_year` equals the year of the claim's `period_month`, else `ERR_NO_FUND_FOR_PERIOD` (HTTP 422). The recomputed `final_amount_cents` must fit within that fund's `available_cents`, else `ERR_FUND_INSUFFICIENT` (HTTP 402). And the merchant's monthly cap must hold: the sum of `final_amount_cents` over the merchant's other `APPROVED` claims for the same `period_month`, plus this claim's final amount, must not exceed the merchant's `monthly_reimbursement_cap_cents`, else `ERR_MERCHANT_MONTHLY_CAP_EXCEEDED` (HTTP 422). On approval the claim stores `final_amount_cents` and binds `program_fund_id` to the resolved fund, the fund's `paid_cents` increases by the final amount — a fund mutation that increments the fund's `version` — and the merchant's `current_month_reimbursed_cents` is recomputed as the sum of `final_amount_cents` over the merchant's `APPROVED` claims whose approval timestamp falls inside the clock's current calendar month. Denial is the administrator's alternative on a `SUBMITTED` claim (otherwise `ERR_CLAIM_NOT_SUBMITTED`): a `reason` is required (its absence is an `ERR_INVALID_REQUEST`), the claim moves to `DENIED`, and `denial_reason` records it — either the supplied reason or `MERCHANT_TERMINATED` when the termination cascade of §3.5 denies the claim. A merchant's claim history can be listed with an optional `status` filter.

## 4. Endpoint Definitions

Operations that create a new resource — an application, a document, a card, a merchant, an offer, a fee waiver grant, a usage transaction, a program fund, or a reimbursement claim — return `201 Created` with the created resource in the response. Operations that modify an existing resource, including all state transitions and the clock-control capability, return `200 OK` with the updated resource (or, for the clock, the resulting `current_utc`). All reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/senior-benefits/_clock/set_current_utc` | Set the logical clock; applies all due time-based transitions | ProgramAdministrator |
| POST | `/senior-benefits/applications` | Submit an INITIAL or RECERTIFICATION application; eligibility gates evaluated at submission | Applicant, Cardholder |
| GET | `/senior-benefits/applications/{id}` | Read one application | Applicant, EligibilitySpecialist, ProgramAdministrator, FraudAnalyst |
| POST | `/senior-benefits/applications/{id}/start-review` | Begin or resume eligibility review | EligibilitySpecialist |
| POST | `/senior-benefits/applications/{id}/request-info` | Send the application back for more information | EligibilitySpecialist |
| POST | `/senior-benefits/applications/{id}/approve` | Approve an application under review; enrolls or recertifies | ProgramAdministrator |
| POST | `/senior-benefits/applications/{id}/deny` | Deny an application under review | ProgramAdministrator |
| POST | `/senior-benefits/applications/{id}/documents` | Attach a verification document to an application | Applicant, Cardholder |
| GET | `/senior-benefits/applications/{id}/documents` | List an application's verification documents | Applicant, EligibilitySpecialist, ProgramAdministrator, FraudAnalyst |
| POST | `/senior-benefits/applications/{id}/documents/{docId}/review` | Verify or reject a submitted document | EligibilitySpecialist |
| GET | `/senior-benefits/cardholders/{id}` | Read one cardholder, including computed standing and year-to-date figures | Cardholder, EligibilitySpecialist, ProgramAdministrator, FraudAnalyst |
| GET | `/senior-benefits/cardholders/{id}/applications` | List a cardholder's applications | Cardholder, EligibilitySpecialist, ProgramAdministrator |
| POST | `/senior-benefits/cardholders/{id}/cards` | Issue a REPLACEMENT or RENEWAL card (OCC-guarded on the cardholder version) | Cardholder, ProgramAdministrator |
| GET | `/senior-benefits/cardholders/{id}/cards` | List a cardholder's cards in all statuses | Cardholder, ProgramAdministrator, FraudAnalyst, EligibilitySpecialist |
| POST | `/senior-benefits/cardholders/{id}/revoke` | Permanently revoke program membership | FraudAnalyst |
| POST | `/senior-benefits/cardholders/{id}/fee-waivers` | Grant a transit or facility fee waiver over a closed date interval | ProgramAdministrator |
| GET | `/senior-benefits/cardholders/{id}/fee-waivers` | List a cardholder's fee waiver grants | Cardholder, ProgramAdministrator, EligibilitySpecialist |
| POST | `/senior-benefits/merchants` | Enroll a participating merchant with reimbursement terms | ProgramAdministrator |
| GET | `/senior-benefits/merchants/{id}` | Read one merchant, including the current month's reimbursed total | MerchantOperator, ProgramAdministrator, FraudAnalyst |
| POST | `/senior-benefits/merchants/{id}/terminate` | Terminate merchant participation; retires offers and denies pending claims | ProgramAdministrator |
| POST | `/senior-benefits/merchants/{id}/offers` | Publish a discount offer with a half-open validity window | MerchantOperator |
| GET | `/senior-benefits/merchants/{id}/offers` | List a merchant's offers | MerchantOperator, ProgramAdministrator, Cardholder, FraudAnalyst |
| POST | `/senior-benefits/usage-transactions` | Record a card-present purchase; resolves the offer, computes the discount, applies velocity rules | MerchantOperator |
| GET | `/senior-benefits/usage-transactions` | List usage transactions with optional filters | MerchantOperator, ProgramAdministrator, FraudAnalyst, Cardholder |
| GET | `/senior-benefits/usage-transactions/{id}` | Read one usage transaction | MerchantOperator, ProgramAdministrator, FraudAnalyst, Cardholder |
| POST | `/senior-benefits/usage-transactions/{id}/void` | Void a POSTED transaction; reverses year-to-date totals | MerchantOperator |
| POST | `/senior-benefits/usage-transactions/{id}/flag` | Manually flag a POSTED transaction for fraud review | FraudAnalyst |
| POST | `/senior-benefits/usage-transactions/{id}/clear-flag` | Clear a flag; the flagging analyst cannot clear their own manual flag | FraudAnalyst |
| POST | `/senior-benefits/program-funds` | Create the annual program fund for a fiscal year | ProgramAdministrator |
| GET | `/senior-benefits/program-funds/{id}` | Read a program fund's paid and available balances | ProgramAdministrator, FraudAnalyst |
| POST | `/senior-benefits/merchants/{id}/reimbursement-claims` | File a monthly reimbursement claim; provisional amount frozen at submission | MerchantOperator |
| GET | `/senior-benefits/merchants/{id}/reimbursement-claims` | List a merchant's reimbursement claims | MerchantOperator, ProgramAdministrator, FraudAnalyst |
| POST | `/senior-benefits/reimbursement-claims/{id}/approve` | Approve a claim; recomputes the final amount, binds and debits the fund, enforces the monthly cap | ProgramAdministrator |
| POST | `/senior-benefits/reimbursement-claims/{id}/deny` | Deny a SUBMITTED claim | ProgramAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CARDHOLDER_NOT_FOUND` | 404 Not Found |
| `ERR_CARD_NOT_FOUND` | 404 Not Found |
| `ERR_MERCHANT_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSACTION_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_FUND_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_DOCUMENT_ALREADY_REVIEWED` | 409 Conflict |
| `ERR_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARDHOLDER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARDHOLDER_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_MERCHANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_TRANSACTION_NOT_FLAGGABLE` | 409 Conflict |
| `ERR_TRANSACTION_NOT_VOIDABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_MERCHANT_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_CARDHOLDER_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_VELOCITY_HARD_LIMIT` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_OFFER_WINDOW_INVALID` | 400 Bad Request |
| `ERR_WAIVER_WINDOW_INVALID` | 400 Bad Request |
| `ERR_OFFER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WAIVER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CLAIM_PERIOD_NOT_CLOSED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_FISCAL_YEAR` | 409 Conflict |
| `ERR_DUPLICATE_PENDING_APPLICATION` | 409 Conflict |
| `ERR_DUPLICATE_PENDING_CLAIM` | 409 Conflict |
| `ERR_RECERTIFICATION_NOT_DUE` | 409 Conflict |
| `ERR_REPLACEMENT_NOT_ALLOWED` | 409 Conflict |
| `ERR_ELIGIBILITY_AGE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_ELIGIBILITY_INCOME_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MISSING_REQUIRED_DOCUMENTS` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_OFFER` | 422 Unprocessable Entity |
| `ERR_NO_FUND_FOR_PERIOD` | 422 Unprocessable Entity |
| `ERR_FUND_INSUFFICIENT` | 402 Payment Required |
| `ERR_MERCHANT_MONTHLY_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
