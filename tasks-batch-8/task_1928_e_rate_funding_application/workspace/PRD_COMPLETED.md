# E-Rate Funding Application API — Product Requirements Document

## 1. Introduction

Schools and libraries across the country depend on the E-Rate program to afford broadband connectivity and the internal equipment that carries it to classrooms and reading rooms. The program's pipeline is long and heavily regulated: an applicant must inventory eligible services for the funding year, run a competitive procurement with a mandatory 28-day bidding window in which price must be the primary evaluation factor, certify a contract with the winning vendor, file a funding request whose discount rate is derived from student lunch-program eligibility, survive Program Integrity Assurance review, and only then begin invoicing — either claiming reimbursement for bills the applicant already paid, or letting the vendor claim the discounted share directly. Service substitutions, appeals of adverse decisions, and a ten-year document retention obligation round out the compliance surface.

This API operationalizes that entire pipeline as a deterministic, audit-ready service. It enforces the program's structural safeguards — segregation of duties between bid selection and contract certification, and between review and commitment staff; a Category Two budget pool per applicant with a statutory floor; pinned discount snapshots that freeze an applicant's rate at filing time; and automatic document retention with auditor-managed holds and purge gating. All date-sensitive rules read a single logical clock so that windows, deadlines, and retention horizons behave identically in every environment. The audience is the engineering team building this service; this document is the sole specification they should need.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, conventions, and boilerplate that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. Nine operational roles are recognized: `ProgramAdmin`, `ApplicantCoordinator`, `ApplicantCertifier`, `VendorRepresentative`, `PIAReviewer`, `CommitmentOfficer`, `InvoiceProcessor`, `AppealOfficer`, and `Auditor`. A tenth designation, `Any`, appears on read endpoints to denote that every authenticated role may call them. A request that omits either header, or presents a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); a role value outside the nine recognized roles counts as malformed. When the caller's role is not in the endpoint's authorized list, the rejection is `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `ApplicantCoordinator` or `ApplicantCertifier`, `X-User-ID` is the `id` of the acting `ApplicantUser`; ownership checks on any resource that traces back to an applicant — a posting, contract, funding request, funding request line, invoice, or appeal — compare that user's `applicant_id` against the resource's applicant chain, and a mismatch is rejected with `ERR_APPLICANT_ACCESS_DENIED` (HTTP 403). When `X-User-Role` is `VendorRepresentative`, `X-User-ID` is the `id` of the acting `ServiceProvider`; ownership checks compare that provider against the provider of the contract behind an SPI invoice, and on resubmission against the invoice's recorded submitting provider, with mismatches rejected as `ERR_PROVIDER_ACCESS_DENIED` (HTTP 403). Bid submission is the one exception to provider ownership scoping: any registered provider may bid on any open posting. For the remaining roles — `ProgramAdmin`, `PIAReviewer`, `CommitmentOfficer`, `InvoiceProcessor`, `AppealOfficer`, and `Auditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, appending a reviewer's identifier to `pia_reviewer_user_ids` on a funding request, or storing it as `decided_by_user_id` when a decision is issued), but it never compares such an identifier to any entity's `id`. An `X-User-ID` that resolves to no persisted entity — a nonexistent `ApplicantUser` id under an applicant role, or a nonexistent `ServiceProvider` id under `VendorRepresentative` — matches no applicant or provider, so every ownership-scoped call from such an identity is denied (`ERR_APPLICANT_ACCESS_DENIED` or `ERR_PROVIDER_ACCESS_DENIED` respectively), while unscoped reads remain open to it.

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

Requests to an undefined path, or to a defined path with an unsupported method, are rejected in the same envelope with `ERR_NOT_FOUND` (HTTP 404); any other unexpected failure surfaces as `ERR_INVALID_REQUEST` (HTTP 400).

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. An empty value is treated as absent; a non-empty value that does not parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`.

### 2.4. The Logical Clock and the Program Calendar

Every window, deadline, and retention rule in this API reads a single logical clock — never the wall clock. At startup, before any call has been made, the logical clock stands at exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `ProgramAdmin`-only operation (`POST /erate/_clock/set_current_utc`) sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The supplied instant may carry any UTC offset (a missing offset is read as UTC), is normalized to whole-second UTC precision, and may be earlier or later than the clock's current value; the returned `current_utc` is rendered as `YYYY-MM-DDTHH:MM:SSZ`. Advancing the clock fires no entity mutations on its own; every window and deadline is evaluated lazily, at the moment the operation it guards is attempted.

Two interval conventions recur throughout the program calendar. A **closed interval** includes both boundary dates; a **half-open interval** includes its start and excludes its end. Date-granularity rules use the logical clock's UTC calendar date, and all date arithmetic is performed in calendar days; the bid window alone is timestamp-exact.

- The **bid window** on a published posting is the half-open interval from `posted_at` up to but not including `window_close_at`, which is exactly 28 days after `posted_at`. A bid submitted at exactly `window_close_at` is already late and is rejected with `ERR_BID_WINDOW_CLOSED`.
- The **window-closure gate**: closing the bidding early is impossible — the operation requires the clock to be at or beyond `window_close_at`, and otherwise fails with `ERR_BID_WINDOW_STILL_OPEN`.
- The **filing window** of a funding cycle is the closed interval from `window_open_date` through `window_close_date`. Certifying a funding request on the closing date itself is allowed; anything outside the interval is `ERR_FILING_WINDOW_CLOSED`.
- The **appeal window** is the closed interval from a request's `decision_date` through 60 days after it. Filing on day 60 is allowed; filing on day 61 or later is `ERR_APPEAL_WINDOW_PASSED`.
- The **invoice deadline** is closed: an invoice may be submitted on or before its line's `invoice_deadline_date`, which is set at commitment to 120 days after the cycle's `service_delivery_deadline`. A later submission is `ERR_INVOICE_DEADLINE_PASSED`.
- The **retention horizon** of a document is its `retained_until_date`, computed as the cycle's `service_delivery_deadline` plus ten years, keeping the same month and day in a leap-safe manner. Purging requires the clock's date to be strictly greater than `retained_until_date` — purging on that date itself is forbidden (`ERR_DOCUMENT_NOT_PURGEABLE`). Audit-hold containment is the half-open interval from `hold_start_date` up to but not including `hold_end_date`, so purging on `hold_end_date` itself is permitted.

### 2.5. Common Resource Properties and Entity Versioning

Every primary resource carries a standard set of system-managed properties:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set once at creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on any change to the resource.
- `version` — a system-managed integer that starts at 1 at creation and increments by exactly 1 on every mutation of the resource, including mutations the server applies as cascade side effects on a related resource (for example, a disbursement that advances the funding line's ledger also advances the line's `version`).

One deliberate exception exists. An NSLP eligibility snapshot is an append-only fact: it carries only `id` and `created_at`, and both `updated_at` and `version` are absent, because snapshots are never mutated after recording — a newer snapshot simply supersedes an older one by recency.

### 2.6. Money, Percentages, and Rounding Discipline

All monetary amounts in the API are integer cents. Fields such as `eligible_price_cents`, `total_eligible_cents`, `requested_pre_discount_cents`, `committed_pre_discount_cents`, `committed_share_cents`, `gross_invoiced_cents`, `applicant_paid_cents`, `approved_reimbursement_cents`, `reimbursed_cents`, `remaining_reimbursable_cents`, and `committed_total_share_cents` are whole numbers of cents; fractional cents never appear.

Discount shares — `effective_share_pct` on a snapshot and its pinned copy `nslp_share_pct` on a funding request — are percentages carried to exactly 2 decimal places, rounded half up. Discount rates (`discount_rate_c1_pct`, `discount_rate_c2_pct`) and bid evaluation weights (`price_weight_pct`, each factor's `weight_pct`) are integer percents. A bid's `total_score` is a number computed to 2 decimal places, with round-half-up applied per component and again to the total. Reimbursement and commitment shares are rounded half up to integer cents **per funding line before any summation** — a pinned rounding order detailed in §3.5.

### 2.7. Optimistic Concurrency Control

Two write operations participate in optimistic concurrency control; no other endpoint accepts a version field.

1. **PIA responses.** A `POST /erate/funding-requests/{id}/pia-responses` request must carry `expected_request_version`, holding the applicant's last-observed `version` of the funding request. If the request's current `version` has advanced beyond that value — for instance because a reviewer issued a further information request, a self-loop that legitimately advances `version` while leaving the `INFORMATION_REQUESTED` status unchanged — the response is predicated on a stale review round and is rejected with `ERR_STALE_VERSION` (HTTP 412).
2. **Service substitutions.** A `POST /erate/service-substitutions` request must carry `expected_line_version`, holding the coordinator's last-observed `version` of the funding request line. If the line's current `version` has advanced — for instance because a prior substitution on the same line was just approved, rewriting the line's eligible service and bumping its `version` — the new substitution's from-service premise is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.8. Segregation of Duties and Audit Holds

Two segregation-of-duties rules separate the people who evaluate from the people who finalize. When a posting's winner is selected, the caller's `X-User-ID` is recorded as the posting's `selected_by_user_id`; the contract growing out of that posting must later be certified by a different user, and a certifier whose identifier matches `selected_by_user_id` is rejected with `ERR_SOD_CONTRACT_CERTIFIER` (HTTP 409). Symmetrically, every `PIAReviewer` who opens review or issues an information request on a funding request is recorded in the request's `pia_reviewer_user_ids`; the commitment decision must come from a `CommitmentOfficer` whose identifier does not appear in that list, and otherwise the decision is rejected with `ERR_SOD_COMMITMENT_OFFICER` (HTTP 409).

An `Auditor` may place or lift an applicant-level audit hold by supplying `active`; the flag is stored as `audit_hold_active` on the applicant (initially `false` at registration) and every set-audit-hold call increments the applicant's `version` by 1, whether or not the flag's value actually changes. While an applicant's hold is active, approval of any invoice against that applicant's funding lines is blocked with `ERR_AUDIT_HOLD_ACTIVE` (HTTP 409) — and this compliance check is evaluated before any fiscal comparison, so a held applicant never reaches the reimbursement-arithmetic stage. Document-level audit holds are a separate, per-document mechanism described in §3.9.

### 2.9. Automatic Document Retention

Seven business events automatically create a **RetainedDocument** record as part of the same atomic request that caused them: contract certification (`document_kind` `CONTRACT_CERTIFICATION`), contract termination (`CONTRACT_TERMINATION`), funding-request certification (`REQUEST_CERTIFICATION`), every commitment decision whichever its outcome (`COMMITMENT_DECISION`), invoice disbursement (`DISBURSEMENT_RECORD`), substitution approval (`SUBSTITUTION_APPROVAL`), and every appeal decision (`APPEAL_DECISION`). Each record carries a `subject_type` — one of `CONTRACT`, `FUNDING_REQUEST`, `INVOICE_SUBMISSION`, `SERVICE_SUBSTITUTION`, or `APPEAL` — together with a polymorphic `subject_id` holding the identifier of the subject entity, and a `funding_cycle_id` resolved through the subject so that retention is always anchored to a cycle. The `retained_until_date` follows the ten-year rule of §2.4. Document listings may be filtered by `subject_type`, `subject_id`, `funding_cycle_id`, or `status`. The hold-and-purge lifecycle (`RETAINED`, `HELD`, `PURGED`) is specified in §3.9.

### 2.10. Validation Order

When several checks could reject the same call, the server evaluates them in a fixed priority order so that the surfaced error is deterministic:

1. **Header presence and form** — missing or malformed `X-User-ID` / `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — a caller whose role is not in the endpoint's authorized list yields `ERR_FORBIDDEN_FOR_ROLE`.
3. **Ownership scope** — applicant-chain mismatches yield `ERR_APPLICANT_ACCESS_DENIED`; provider mismatches on SPI invoices yield `ERR_PROVIDER_ACCESS_DENIED`. Bid creation is exempt from this tier.
4. **Request shape and required fields** — unknown or missing fields, bad enum members, non-positive amounts, malformed dates, and violated conditional-field rules all yield `ERR_INVALID_REQUEST`. This tier covers: a BEAR invoice without `applicant_paid_cents`; an SPI invoice carrying `applicant_paid_cents`; a snapshot with `cep_participating` true but no `cep_identified_student_pct`; a `SCHOOL` applicant without `student_count`; a `LIBRARY` applicant without `square_feet`; a snapshot whose `free_lunch_eligible_students` exceeds its `total_students`; a hold whose `hold_end_date` does not fall strictly after its `hold_start_date`; a cycle whose `window_close_date` precedes its `window_open_date`; a contract whose `service_end_date` precedes its `service_start_date`; bid `factor_scores` that do not cover exactly the posting's factor set; a contract `total_eligible_cents` that differs from the price of the bid referenced by the request's `winning_bid_id`; and a duplicate `spin`.
5. **Referenced-id existence** — every identifier in the path and body must exist, validated left to right: path parameters first, then body fields in their declared order. The first missing identifier yields `ERR_NOT_FOUND`. Checks that cannot be evaluated without the referenced entity — an ownership scope keyed off a body-supplied identifier, a bid's `factor_scores` coverage of its posting's factor set, or a contract ceiling's equality with the referenced bid's price — are evaluated only once that reference has resolved, so a missing reference yields `ERR_NOT_FOUND` ahead of them.
6. **State gates** — the target resource must be in a from-state of the invoked transition, or satisfy the state gate of a state-gated create: a certified contract for line creation, a committed line plus started services for invoice creation, a denied request for appeal filing, an awarded posting for contract creation. Violations yield `ERR_INVALID_STATE_TRANSITION`, or the more specific `ERR_CONTRACT_NOT_CERTIFIED`, `ERR_LINE_NOT_COMMITTED`, or `ERR_SERVICES_NOT_STARTED` where those named gates apply.
7. **Optimistic concurrency** — the two OCC-guarded writes of §2.7 yield `ERR_STALE_VERSION` on a version mismatch.
8. **Compliance gates** — segregation of duties and applicant audit holds: `ERR_SOD_CONTRACT_CERTIFIER`, `ERR_SOD_COMMITMENT_OFFICER`, and `ERR_AUDIT_HOLD_ACTIVE`. Compliance is deliberately evaluated ahead of the temporal, structural, and fiscal tiers.
9. **Temporal windows** — the window and deadline rules of §2.4: `ERR_BID_WINDOW_CLOSED`, `ERR_BID_WINDOW_STILL_OPEN`, `ERR_FILING_WINDOW_CLOSED`, `ERR_APPEAL_WINDOW_PASSED`, and `ERR_INVOICE_DEADLINE_PASSED`.
10. **Structural business rules** — `ERR_PRICE_NOT_PRIMARY`, `ERR_CONTRACT_TERM_OVERLAP`, `ERR_NO_QUALIFIED_BIDS`, `ERR_SERVICE_NOT_ELIGIBLE`, `ERR_SUBSTITUTION_CATEGORY_MISMATCH`, `ERR_APPEAL_ALREADY_ACTIVE`, `ERR_EMPTY_REQUEST`, and `ERR_DOCUMENT_NOT_PURGEABLE`.
11. **Cross-entity referential consistency** — `ERR_BID_NOT_AWARDED`, `ERR_CROSS_ENTITY_MISMATCH`, and `ERR_DISCOUNT_SNAPSHOT_MISSING`.
12. **Fiscal checks last** — contract capacity and reimbursement ceiling: `ERR_CONTRACT_CAPACITY_EXCEEDED` and `ERR_REIMBURSEMENT_EXCEEDS_REMAINING` are evaluated only after every other tier has passed.

## 3. Business Logic & Workflows

### 3.1. Establishing the Program Year: Cycles, Inventory, Applicants, and Providers

Every funding year begins with a `ProgramAdmin` provisioning the **FundingCycle**: a free-text `label` (for example, `FY2027`; uniqueness is not enforced), a `window_open_date` and a `window_close_date` that bound the filing window as a closed interval, and a `service_delivery_deadline` that later anchors both invoice deadlines (120 days beyond it) and document retention (ten years beyond it). All three dates use the `YYYY-MM-DD` format. A cycle whose closing date precedes its opening date is rejected with `ERR_INVALID_REQUEST`.

Alongside the cycle, the administrator publishes the year's **eligible services inventory**. Each entry carries the `funding_cycle_id` of the cycle it belongs to, a free-text `service_description` (for example, "Wireless Access Points"), a `category` of `CATEGORY_ONE` or `CATEGORY_TWO`, and a `service_type` drawn from `INTERNET_ACCESS`, `DATA_TRANSMISSION`, `VOICE_SERVICE`, `INTERNAL_CONNECTIONS`, or `BASIC_MAINTENANCE`. Inventory listings support reverse lookup by `funding_cycle_id` and `category`.

Applicant registration captures the billed entity's `name`, an `entity_type` of `SCHOOL` or `LIBRARY`, and an `urban_rural` designation of `URBAN` or `RURAL` — the last of these matters later, because the discount matrix keys on it. Enrollment and size are conditional: a `SCHOOL` must supply `student_count` greater than zero, while a `LIBRARY` must instead supply `square_feet` greater than zero; omitting the required measure is `ERR_INVALID_REQUEST`. Every applicant starts life with `audit_hold_active` set to `false`. Applicant listings may be filtered by `entity_type`.

Each applicant's staff is provisioned as **ApplicantUser** records carrying the `applicant_id` they act for, a `display_name`, and a `function` of `COORDINATOR` or `CERTIFIER` — the two applicant-side capacities that drive procurement and certification respectively; the recorded `function` is descriptive only, and authorization is governed by the presented `X-User-Role` header, never cross-checked against it. Listings of users may be filtered by `applicant_id`. Vendors are registered as **ServiceProvider** records with a `name` and a `spin` (service provider identification number); the `spin` must be unique across the program, and a duplicate registration is rejected with `ERR_INVALID_REQUEST`.

### 3.2. Measuring Need: Snapshots, Discount Rates, and the Category Two Budget

An applicant's discount rate flows from its lunch-program eligibility, recorded as an **NSLPSnapshot** for a given (`applicant_id`, `funding_cycle_id`) pair. A snapshot carries `total_students` (greater than zero), `free_lunch_eligible_students` (at least zero and never greater than `total_students` — a larger count is `ERR_INVALID_REQUEST`), a `cep_participating` flag, and a `cep_identified_student_pct` between 0 and 100 that is required when that flag is true (a participating snapshot without it is `ERR_INVALID_REQUEST`) and, when the flag is false, is still accepted, validated, and stored but plays no role in the share computation. At recording time the server computes the snapshot's `effective_share_pct`, and it does so one of two ways, depending on the variant:

- **Direct certification.** When `cep_participating` is false, the share is 100 times `free_lunch_eligible_students` divided by `total_students`, rounded half up to two decimal places.
- **CEP projection.** When `cep_participating` is true, the share is `cep_identified_student_pct` multiplied by 1.6, capped at 100.00 — so an identified percentage of 62.50 or higher saturates the cap.

Both variants then feed the same discount matrix, yet identical cohorts can yield different shares — and therefore different rates — depending on the variant. The effective snapshot for any applicant-and-cycle pair is the latest one by `created_at`; because timestamps carry millisecond precision and snapshots are recorded sequentially, ties cannot occur. As noted in §2.5, snapshots are append-only and carry no `updated_at` or `version`. Snapshot listings may be filtered by `applicant_id` or `funding_cycle_id`.

The **discount matrix** maps the effective share into an integer percentage rate, keyed by service category and the applicant's `urban_rural` designation. The share falls into the first band whose lower bound it meets or exceeds and whose upper bound it falls short of; the top band is closed at 100:

| Effective share (percent) | `CATEGORY_ONE` `URBAN` | `CATEGORY_ONE` `RURAL` | `CATEGORY_TWO` `URBAN` | `CATEGORY_TWO` `RURAL` |
| --- | --- | --- | --- | --- |
| at least 0, less than 1 | 20 | 25 | 20 | 25 |
| at least 1, less than 20 | 40 | 50 | 40 | 50 |
| at least 20, less than 35 | 50 | 60 | 50 | 60 |
| at least 35, less than 50 | 60 | 70 | 60 | 70 |
| at least 50, less than 75 | 80 | 80 | 80 | 80 |
| at least 75, at most 100 | 90 | 90 | 85 | 85 |

Boundary behavior is exact: a share of exactly 35.00 enters the fourth band and yields a Category One urban rate of 60, while 34.99 — one centile below — stays in the third band at 50.

Alongside the discount rate stands the applicant's **Category Two budget pool**, a five-year-style envelope computed from the applicant's size. For a `SCHOOL`, the pool cap is the greater of 16,700 cents (that is, $167.00) per enrolled student times `student_count`, or a floor of 2,500,000 cents ($25,000). For a `LIBRARY`, the cap is the greater of 450 cents ($4.50) per square foot times `square_feet`, or the same 2,500,000-cent floor. Consider a 3,000-square-foot library: its computed 1,350,000 cents lands on the floor at 2,500,000, while a 1,000-student school's 16,700,000 cents comfortably exceeds it. The **committed** side of the pool is the sum of `committed_pre_discount_cents` over the applicant's `CATEGORY_TWO` funding lines currently in `COMMITTED` status — `PENDING` and `DENIED` lines never consume budget, and `CANCELLED` lines have released whatever they held. The **available** budget is the cap minus the committed amount, and the server maintains the invariant that the cap always equals committed plus available.

A computed budget-summary read on an applicant, given a `funding_cycle_id` query parameter that is required (its absence is `ERR_INVALID_REQUEST`, and an unknown applicant id is `ERR_NOT_FOUND`), returns all of this live — `c2_cap_cents`, `c2_committed_cents`, and `c2_available_cents` from the budget pool, plus `discount_rate_c1_pct`, `discount_rate_c2_pct`, and `nslp_share_pct` from a fresh run of the discount lookup against the latest snapshot. Nothing is pinned by this read, and when no snapshot exists for the pair it fails with `ERR_DISCOUNT_SNAPSHOT_MISSING`.

### 3.3. Competitive Bidding and Vendor Selection

Procurement begins when an `ApplicantCoordinator` creates a **ProcurementPosting** — the Form 470 equivalent — with the `applicant_id` and `funding_cycle_id` it belongs to, a `category`, a free-text `description` of the requested services, and the evaluation weights. Price must be the primary factor: `price_weight_pct` is an integer greater than zero and at most 100, and it must be at least the `weight_pct` of every entry in `other_factor_weights` (an optional list of `{ factor_name, weight_pct }` records that defaults to an empty list; each `factor_name` is a non-empty string and each `weight_pct` an integer with no further range constraint). A posting whose price weight falls below any other factor's weight is rejected with `ERR_PRICE_NOT_PRIMARY`. New postings start in `DRAFT` status with `posted_at` null and `selected_bid_id` unset. Posting listings may be filtered by `applicant_id`, `funding_cycle_id`, or `status`.

Publishing transitions the posting from `DRAFT` to `POSTED`: `posted_at` is stamped from the logical clock, `window_close_at` is computed as exactly 28 days later, and the posting's `version` increments. During the half-open window that follows, a `VendorRepresentative` may submit a **Bid** carrying the `posting_id`, an `eligible_price_cents` greater than zero, an optional `ineligible_price_cents` defaulting to 0 (never negative), and `factor_scores` — a list of `{ factor_name, score }` entries whose `factor_name` set must cover exactly the posting's other-factor set, with each `score` an integer from 0 to 100; a coverage mismatch is `ERR_INVALID_REQUEST`. The bidding provider's `service_provider_id` is always taken from the caller's identity, never from the request body, and bid submission is open to any registered provider. A bid arriving at or after `window_close_at` — exactly at the close is already late — is rejected with `ERR_BID_WINDOW_CLOSED`. New bids start `SUBMITTED`, with `total_score` null until evaluation. Bid listings may be filtered by `posting_id`, `service_provider_id`, or `status`.

The coordinator then curates the candidate pool. Qualifying moves a bid from `SUBMITTED` to `QUALIFIED`; disqualifying moves a `SUBMITTED` or `QUALIFIED` bid to `DISQUALIFIED` — with an optional `reason` that is accepted but not stored — but a `QUALIFIED` bid can no longer be disqualified once its posting has been awarded, and any out-of-state attempt draws `ERR_INVALID_STATE_TRANSITION`. Each adjudication increments the bid's `version`.

Closing the window is a separate, deliberate act: it transitions the posting from `POSTED` to `WINDOW_CLOSED` and is permitted only once the clock has reached `window_close_at`; earlier attempts fail with `ERR_BID_WINDOW_STILL_OPEN`. A coordinator may also cancel a posting while it is `DRAFT` or `POSTED`, moving it to `CANCELLED`; cancelling a `POSTED` posting cascades downward, driving every `SUBMITTED` and `QUALIFIED` bid on it to `DISQUALIFIED`, while the posting's own `version` increments.

Winner selection — available to either an `ApplicantCoordinator` or an `ApplicantCertifier` — moves the posting from `WINDOW_CLOSED` to `AWARDED`. It requires at least one `QUALIFIED` bid; an empty candidate pool is rejected with `ERR_NO_QUALIFIED_BIDS`. Evaluation runs only over `QUALIFIED` bids (`SUBMITTED` and `DISQUALIFIED` bids are excluded from the candidate set and from the price floor). First the lowest `eligible_price_cents` among the candidates is found. Each candidate's **price points** are that lowest price divided by the candidate's own `eligible_price_cents`, multiplied by the posting's `price_weight_pct`, and rounded half up to two decimal places. Each candidate's **factor points** are the sum, over every entry in the posting's `other_factor_weights`, of that entry's `weight_pct` multiplied by the bid's `score` for that `factor_name` and divided by 100, each term exact to two decimal places. The bid's `total_score` is the sum of price points and factor points, rounded half up to two decimal places. The winner is the highest `total_score`; ties break to the lower `eligible_price_cents`, and further ties to the earlier bid `created_at`. Because the price weight must be at least every other factor's weight and price points fall away quadratically with relative price, non-price factors can only break near-ties — price is structurally primary.

Selection writes the outcome everywhere it matters at once: the winning bid becomes `SELECTED`, every other `QUALIFIED` bid becomes `NOT_SELECTED`, and `SUBMITTED` or `DISQUALIFIED` bids are untouched. The posting records `selected_bid_id` and the caller's identifier as `selected_by_user_id` — the segregation-of-duties hook that §2.8's contract-certification rule keys on — and the posting's `version` increments. `AWARDED` is terminal.

### 3.4. Contracts: Certification, Overlap, and Termination

From an awarded posting, an `ApplicantCoordinator` drafts a **Contract**, supplying `applicant_id`, `service_provider_id`, `posting_id`, `winning_bid_id`, `category`, `total_eligible_cents`, and the term bounds `service_start_date` and `service_end_date`. The creation-time checks are referential before they are fiscal. The posting must be `AWARDED` — drafting against a posting in any other state is `ERR_INVALID_STATE_TRANSITION`. The `winning_bid_id` must equal the posting's `selected_bid_id`, else `ERR_BID_NOT_AWARDED`. The `service_provider_id` must be the winning bid's provider, the `category` must equal the posting's category, and the `applicant_id` must equal the posting's applicant, with any mismatch rejected as `ERR_CROSS_ENTITY_MISMATCH`. The `total_eligible_cents` ceiling must equal the `eligible_price_cents` of the bid referenced by `winning_bid_id`, and the term's end must not precede its start; either violation is `ERR_INVALID_REQUEST`. Finally, the term must not collide — under closed-interval semantics, so a shared endpoint date counts as overlap — with the term of any other `CERTIFIED` contract for the same (`applicant_id`, `service_provider_id`, `category`) triple; a collision is `ERR_CONTRACT_TERM_OVERLAP`. A drafted contract starts in `DRAFT` status with `certified_date` and `certified_by_user_id` null. Contract listings may be filtered by `applicant_id`, `service_provider_id`, `posting_id`, `winning_bid_id`, or `status`.

Certification is the certifier's act, and it is where segregation of duties bites. An `ApplicantCertifier` certifies a `DRAFT` contract, provided the caller's `X-User-ID` differs from the posting's `selected_by_user_id` — the user who picked the winner may not certify the resulting contract, and the attempt is `ERR_SOD_CONTRACT_CERTIFIER`. The closed-interval overlap check against other `CERTIFIED` contracts with the same applicant, provider, and category is run again at this point, since competing contracts may have certified since drafting. A successful certification sets `certified_date` to the clock's date, records the caller as `certified_by_user_id`, increments the contract's `version`, and creates a `CONTRACT_CERTIFICATION` retained document in the same request.

Termination unwinds everything the contract feeds, atomically within the terminating request. An `ApplicantCertifier` terminates a `CERTIFIED` contract — optionally with a `reason` that is accepted but not stored — moving it to `TERMINATED`, and three cascades follow in order. First, every funding request line whose `contract_id` is this contract and whose status is `PENDING` or `COMMITTED` moves to `CANCELLED` with `denial_reason` `CONTRACT_TERMINATED`; on a cancelled `COMMITTED` line, `remaining_reimbursable_cents` is forced to 0 while `reimbursed_cents` is preserved as historical record. Second, for each cancelled `CATEGORY_TWO` line, the applicant's Category Two committed ledger is released by that line's `committed_pre_discount_cents`, and every affected funding request's `committed_total_share_cents` is recomputed over its remaining `COMMITTED` lines — a request whose recomputed total is unchanged and which does not close is left untouched, its `version` not advancing. Third, any `COMMITTED` funding request left with zero `COMMITTED` lines moves to `CLOSED`. Each cancelled line's `version` increments, the terminated contract's `version` increments, and a `CONTRACT_TERMINATION` retained document is created.

### 3.5. The Funding Request: Lines, Filing, Review, and Decision

With contracts certified, the coordinator assembles the **FundingRequest** — the Form 471 equivalent — created with just `applicant_id` and `funding_cycle_id`, starting in `DRAFT` status with `services_started` false, an empty `pia_reviewer_user_ids` list, the computed discount fields (`nslp_share_pct`, `discount_rate_c1_pct`, `discount_rate_c2_pct`) null, `committed_total_share_cents` at 0, and `service_start_date`, `decision_date`, and `decided_by_user_id` null. Request listings may be filtered by `applicant_id`, `funding_cycle_id`, or `status`.

The request's substance lives in its **FundingRequestLine** records. Adding a line requires `funding_request_id`, `contract_id`, `eligible_service_id`, and a `requested_pre_discount_cents` greater than zero. Lines may only be added while the request is `DRAFT` (otherwise `ERR_INVALID_STATE_TRANSITION`); the referenced contract must be `CERTIFIED` (otherwise `ERR_CONTRACT_NOT_CERTIFIED`); and the contract's applicant must be the request's applicant, the referenced service must belong to the request's cycle inventory, and the contract's category must match the service's category — referential violations are `ERR_CROSS_ENTITY_MISMATCH`. The line's own `category` is copied from the eligible service at creation and is immutable thereafter, even if a substitution later rewrites the service reference. A fiscal guard applies at the contract level: the sum of `requested_pre_discount_cents` over the contract's non-`CANCELLED` lines, including the proposed one, must not exceed the contract's `total_eligible_cents`, or the create fails with `ERR_CONTRACT_CAPACITY_EXCEEDED`. New lines start `PENDING` with `committed_pre_discount_cents` and `committed_share_cents` at 0 until decision, `reimbursed_cents` and `remaining_reimbursable_cents` at 0, `invoice_deadline_date` null, and `denial_reason` null. Line listings may be filtered by `funding_request_id`, `contract_id`, `eligible_service_id`, or `status`.

Filing is the certifier's second act. An `ApplicantCertifier` certifies the request, moving it from `DRAFT` to `FILED`. Three gates guard the transition, and they sit in their usual tiers: the clock's date must fall within the cycle's closed filing window (otherwise `ERR_FILING_WINDOW_CLOSED`); the request must contain at least one `PENDING` line (otherwise `ERR_EMPTY_REQUEST`); and an NSLP snapshot must exist for the applicant-and-cycle pair (otherwise `ERR_DISCOUNT_SNAPSHOT_MISSING`). On success, the discount lookup of §3.2 runs against the latest snapshot and **pins** the result on the request: `nslp_share_pct`, `discount_rate_c1_pct`, and `discount_rate_c2_pct` are frozen at filing and never recomputed afterward, even if newer snapshots arrive. A `REQUEST_CERTIFICATION` retained document is created and the request's `version` increments.

Review follows the Program Integrity Assurance loop. A `PIAReviewer` opens review, moving the request from `FILED` to `PIA_REVIEW` and appending the caller's identifier to `pia_reviewer_user_ids`. From `PIA_REVIEW`, an information request carrying `info_request_text` (accepted but not stored) moves the request to `INFORMATION_REQUESTED`; a further information request from `INFORMATION_REQUESTED` is a self-loop within the same review round — the status does not change, but the caller is again appended to `pia_reviewer_user_ids` and the request's `version` advances by 1. The applicant answers through the coordinator, supplying `response_text` (accepted but not stored) together with the OCC guard `expected_request_version` of §2.7: if the request's current version has moved past what the applicant last observed — precisely the situation the self-loop creates — the answer is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful response returns the request from `INFORMATION_REQUESTED` to `PIA_REVIEW` and increments its `version`.

The decision belongs to a `CommitmentOfficer`, who supplies an `outcome` of `COMMITTED` or `DENIED` with an optional `rationale` that is accepted but not stored. Deciding requires the request to be in `PIA_REVIEW` — an outstanding `INFORMATION_REQUESTED` blocks any decision until the applicant responds — and the officer's identifier must not appear in `pia_reviewer_user_ids`, the §2.8 segregation rule enforced as `ERR_SOD_COMMITMENT_OFFICER`.

When the outcome is `COMMITTED`, the server first computes the applicant's Category Two available budget as of the decision, then walks the request's `CATEGORY_TWO` lines in `created_at` ascending order (millisecond timestamps on sequentially created lines, so no ties occur; identifiers are never used as tiebreakers). At each line's turn the allocation is the smaller of the line's `requested_pre_discount_cents` and the budget remaining at that turn; the allocation becomes the line's `committed_pre_discount_cents`, and the remaining budget is reduced by that amount before the next line's turn. A line whose allocation is zero moves to `DENIED` with `denial_reason` `INSUFFICIENT_BUDGET`. `CATEGORY_ONE` lines stand outside the waterfall entirely: their `committed_pre_discount_cents` equals the full requested amount and they draw nothing from the pool. Each surviving line then gets its share: `committed_share_cents` is the committed pre-discount amount multiplied by the request's pinned discount rate for the line's category and divided by 100, rounded half up to integer cents — computed per line, never on aggregates. The request's `committed_total_share_cents` is the sum of the per-line `committed_share_cents` values over its `COMMITTED` lines. The rounding order is pinned: per-line rounding first, then summation; summing pre-discount amounts and rounding once afterward is forbidden. Two 999-cent lines at a 50 percent rate illustrate why — per-line rounding yields 500 plus 500, a 1,000-cent total, where sum-first rounding would yield 999. Every committed line also receives `remaining_reimbursable_cents` equal to its `committed_share_cents` and an `invoice_deadline_date` set 120 days after the cycle's `service_delivery_deadline`. The request records `decision_date` as the clock's date and the caller as `decided_by_user_id`, creates a `COMMITMENT_DECISION` retained document, and increments its `version`. Each line's own `version` increments as its status and commitment fields are written.

When the outcome is `DENIED`, the mirror-image branch runs: every `PENDING` line moves to `DENIED` with `denial_reason` `REQUEST_DENIED` (each line's `version` incrementing), the request's `decision_date` is set to the clock's date, a `COMMITMENT_DECISION` retained document is created, and the request's `version` increments. A denied request is not necessarily final — §3.8's appeal cascade can reverse it.

Two system transitions complete the request's lifecycle. When a contract termination cascade leaves a `COMMITTED` request with no `COMMITTED` lines, the request moves to `CLOSED`, the terminal state. And a `DENIED` request returns to `COMMITTED` only through a granted appeal, per §3.8.

Before any money can move, services must actually begin. Recording service start — the Form 486 equivalent — is a coordinator action and a deliberate self-loop: the request remains `COMMITTED`, `services_started` flips to true, `service_start_date` is set to the clock's date, and the request's `version` increments. The action is available only while the request is `COMMITTED` and `services_started` is still false; any other attempt is `ERR_INVALID_STATE_TRANSITION`. This flag gates invoice creation in §3.6.

### 3.6. Invoicing and Reimbursement

Invoicing runs per committed line, through one of two methods recorded as the invoice's `method`. Under `BEAR`, the applicant has paid the vendor in full or in part and claims reimbursement; under `SPI`, the vendor has discounted its bills and claims the program's share directly. Creating an **InvoiceSubmission** takes the `frn_line_id`, the `method`, and a `gross_invoiced_cents` greater than zero, plus the conditional `applicant_paid_cents`: required on a BEAR invoice, where it must be greater than zero and no more than `gross_invoiced_cents`, and forbidden on an SPI invoice, where carrying it at all is `ERR_INVALID_REQUEST`; a null value is treated as absent under both methods.

Who may file follows the method. A BEAR invoice is filed by the applicant's own coordinator, and an `ApplicantUser` from a different organization is refused with `ERR_APPLICANT_ACCESS_DENIED`. An SPI invoice is filed by the representative of the provider on the line's contract, with the invoice's `submitted_by_provider_id` taken from the caller's identity (it stays null on BEAR invoices); a representative of any other provider is refused with `ERR_PROVIDER_ACCESS_DENIED`. Three further gates apply at creation, in their validation tiers: the line must be `COMMITTED` (otherwise `ERR_LINE_NOT_COMMITTED`); the line's request must have recorded service start (otherwise `ERR_SERVICES_NOT_STARTED`); and the clock's date must be on or before the line's `invoice_deadline_date` — the deadline date itself is allowed — otherwise `ERR_INVOICE_DEADLINE_PASSED`. A new invoice starts `SUBMITTED`, with `approved_reimbursement_cents` null until approval and `rejection_reason` null unless rejected. Invoice listings may be filtered by `frn_line_id`, `submitted_by_provider_id`, `status`, or `method`.

Review and settlement belong to the `InvoiceProcessor`. Opening review moves an invoice from `SUBMITTED` to `UNDER_REVIEW`. Approval moves it from `UNDER_REVIEW` to `APPROVED`, and the approval-time checks run compliance before fiscal, per §2.10: if the applicant's `audit_hold_active` is true, approval is blocked with `ERR_AUDIT_HOLD_ACTIVE` before any amount is examined. Otherwise the server computes the tentative reimbursement: the base is the smaller of `applicant_paid_cents` and `gross_invoiced_cents` for a BEAR invoice — the applicant-fronted amount drives the claim — or the full `gross_invoiced_cents` for an SPI invoice, where the vendor already discounted the bills. The tentative amount is the base multiplied by the request's pinned discount rate for the line's category, divided by 100, and rounded half up to integer cents. Identical inputs therefore produce different results under the two variants: a 40,000-cent bill at a 50 percent rate reimburses 15,000 cents under BEAR when the applicant paid 30,000 of it, but 20,000 cents under SPI. If the tentative amount exceeds the line's `remaining_reimbursable_cents`, approval is rejected with `ERR_REIMBURSEMENT_EXCEEDS_REMAINING`; equality is allowed and drains the remaining balance to exactly 0. A successful approval stores the tentative amount as `approved_reimbursement_cents` and increments the invoice's `version`.

Disbursement moves an `APPROVED` invoice to the terminal `PAID` state and syncs the line's reimbursement ledger in the same request: the approved amount is added to the line's `reimbursed_cents` and subtracted from its `remaining_reimbursable_cents`, so the line's committed share is exactly conserved between paid and remaining portions. Both the line's `version` and the invoice's `version` increment, and a `DISBURSEMENT_RECORD` retained document is created.

Corrections form a review-cycle loop. Rejecting an invoice — which requires a processor-supplied `rejection_reason` — works from two states with two different compensations. From `UNDER_REVIEW`, rejection moves the invoice to `REJECTED` and stores the reason; no money fields ever changed, so nothing is unwound. From `APPROVED`, rejection is a compensating action that revokes the approval before any disbursement: `approved_reimbursement_cents` is cleared back to null, while the line's `reimbursed_cents` and `remaining_reimbursable_cents` remain untouched. Resubmission then returns a `REJECTED` invoice to `UNDER_REVIEW`, clearing `rejection_reason`, but only for the rightful claimant: an SPI invoice may be resubmitted only by a representative of the provider recorded in `submitted_by_provider_id`, and a BEAR invoice only by a user belonging to the line's applicant — violations are refused with the ownership errors of §2.1. Each rejection and resubmission increments the invoice's `version`.

### 3.7. Service Substitutions and Supersede Chains

Commitments sometimes need to swap one eligible service for another — same cycle, same category, different inventory entry. A coordinator requests a **ServiceSubstitution** against a `COMMITTED` line, supplying the `frn_line_id`, the `to_eligible_service_id`, and the OCC guard `expected_line_version` of §2.7, plus an optional `supersedes_substitution_id` and an optional free-text `reason`. The line must be `COMMITTED`; a substitution against a line in any other status is an invalid state transition. If the line's current `version` has advanced beyond `expected_line_version` — classically because a prior substitution on this same line was just approved — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The target service must sit in the same funding cycle's eligible services inventory (otherwise `ERR_SERVICE_NOT_ELIGIBLE`) and must carry the same category as the service being replaced (otherwise `ERR_SUBSTITUTION_CATEGORY_MISMATCH`). When `supersedes_substitution_id` is present, the referenced substitution must currently be `APPROVED` on the same line; anything else is `ERR_CROSS_ENTITY_MISMATCH`. At creation, the substitution snapshots the line's current `eligible_service_id` into its own `from_eligible_service_id`, starts in `REQUESTED` status — and the very act of creating the substitution increments the line's `version` by 1, which is what makes a second substitution's stale-version check meaningful. Substitution listings may be filtered by `frn_line_id`, `supersedes_substitution_id`, `from_eligible_service_id`, `to_eligible_service_id`, or `status`.

The decision belongs to the `ProgramAdmin`. Approval moves the substitution from `REQUESTED` to `APPROVED` and rewrites the line: its `eligible_service_id` becomes the substitution's `to_eligible_service_id`, while all committed amounts on the line stay unchanged. If the substitution named a predecessor in `supersedes_substitution_id`, that predecessor flips from `APPROVED` to `SUPERSEDED` in the same request. Approval also creates a `SUBSTITUTION_APPROVAL` retained document, and increments both the substitution's `version` and the line's `version` by 1. Denial instead moves the substitution from `REQUESTED` to `DENIED`, with an optional `denial_reason` note that is accepted but not stored, incrementing only the substitution's `version`. `DENIED` and `SUPERSEDED` are terminal; `APPROVED` endures until a later substitution supersedes it.

### 3.8. Appeals and the Recommit Cascade

An adverse commitment decision can be appealed. The coordinator files an **Appeal** with the `funding_request_id` and free-text `grounds`. The request must be `DENIED` — appealing a request in any other status is `ERR_INVALID_STATE_TRANSITION` — and only one appeal per request may be non-terminal at a time: if an appeal in `FILED` or `UNDER_REVIEW` already exists for the request, the filing is rejected with `ERR_APPEAL_ALREADY_ACTIVE`. The filing date, stored as `filed_date`, is taken from the logical clock and must fall within the closed window from the request's `decision_date` through 60 days after it; filing on day 60 itself is allowed, while day 61 or later is `ERR_APPEAL_WINDOW_PASSED`. A new appeal starts `FILED` with `outcome_date` null. Appeal listings may be filtered by `funding_request_id` or `status`.

An `AppealOfficer` opens review, moving the appeal from `FILED` to `UNDER_REVIEW`, and later decides it with an `outcome` of `GRANTED` or `DENIED` and an optional `rationale` that is accepted but not stored. Both outcomes set `outcome_date` to the clock's date, create an `APPEAL_DECISION` retained document, and increment the appeal's `version`; `GRANTED` and `DENIED` are both terminal for the appeal.

A grant is where the cascade fires, in three links within the same atomic request. First, the funding request flips from `DENIED` back to `COMMITTED`, its `version` incrementing. Second, each of the request's `DENIED` lines re-runs the commitment machinery of §3.5 against the budget as it stands now: the request's Category Two lines are walked again in `created_at` ascending order, each line's allocation recomputed as the smaller of its `requested_pre_discount_cents` and the currently remaining budget, with the remainder decrementing before the next line's turn. A line whose recomputed allocation exceeds zero moves back to `COMMITTED` with its commitment fields — `committed_pre_discount_cents`, `committed_share_cents`, `remaining_reimbursable_cents`, `invoice_deadline_date` — recomputed against the current budget; a line that again draws zero stays `DENIED` with `denial_reason` `INSUFFICIENT_BUDGET`. Third, the applicant's Category Two committed ledger increases by each recommitted line's `committed_pre_discount_cents`, and the request's `committed_total_share_cents` is recomputed as the sum of the per-line committed shares. A denial of the appeal, by contrast, changes nothing on the funding request — the request remains `DENIED`.

### 3.9. Document Holds, Retention Expiry, and Purge

Every retained document of §2.9 starts its life in `RETAINED` status, with `hold_start_date` and `hold_end_date` both null. An `Auditor` manages the document from there.

Placing an audit hold moves a `RETAINED` document to `HELD`, storing the supplied `hold_start_date` and `hold_end_date` and incrementing the document's `version`; the end date must fall strictly after the start date, and a hold that does not is `ERR_INVALID_REQUEST`. Hold containment is always the half-open interval from `hold_start_date` up to but not including `hold_end_date`. Releasing the hold returns a `HELD` document to `RETAINED` and clears both hold dates back to null, again incrementing the `version`.

Purging is the audit program's final act and is deliberately hard to trigger by accident. From either `RETAINED` or `HELD`, an `Auditor` may purge a document only when the clock's date is strictly greater than `retained_until_date` — purging on the retention date itself is forbidden and draws `ERR_DOCUMENT_NOT_PURGEABLE`. When the document is under a hold, the clock's date must additionally not fall inside the hold's half-open interval; a purge attempted on a covered date fails with `ERR_AUDIT_HOLD_ACTIVE`, while a purge on `hold_end_date` itself is allowed because the interval excludes its end. A successful purge moves the document to the terminal `PURGED` state and increments its `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions — return `200 OK`, as do all reads. The table below is a routing summary only; request payloads, computed fields, validation behavior, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/erate/_clock/set_current_utc` | Set the logical clock | ProgramAdmin |
| POST | `/erate/funding-cycles` | Create a funding cycle | ProgramAdmin |
| GET | `/erate/funding-cycles` | List funding cycles (paginated) | Any |
| GET | `/erate/funding-cycles/{id}` | Get a funding cycle | Any |
| POST | `/erate/eligible-services` | Add an eligible services inventory entry to a cycle | ProgramAdmin |
| GET | `/erate/eligible-services` | List eligible services | Any |
| GET | `/erate/eligible-services/{id}` | Get an eligible service | Any |
| POST | `/erate/applicants` | Register an applicant (school or library) | ProgramAdmin |
| GET | `/erate/applicants` | List applicants (paginated) | Any |
| GET | `/erate/applicants/{id}` | Get an applicant | Any |
| GET | `/erate/applicants/{id}/budget-summary` | Live Category Two budget and discount rates for a cycle | Any |
| POST | `/erate/applicants/{id}/set-audit-hold` | Place or lift an applicant-level audit hold | Auditor |
| POST | `/erate/nslp-snapshots` | Record an NSLP/CEP eligibility snapshot | ProgramAdmin |
| GET | `/erate/nslp-snapshots` | List snapshots | Any |
| GET | `/erate/nslp-snapshots/{id}` | Get a snapshot | Any |
| POST | `/erate/applicant-users` | Provision an applicant user | ProgramAdmin |
| GET | `/erate/applicant-users` | List applicant users | Any |
| GET | `/erate/applicant-users/{id}` | Get an applicant user | Any |
| POST | `/erate/service-providers` | Register a service provider (vendor) | ProgramAdmin |
| GET | `/erate/service-providers` | List service providers (paginated) | Any |
| GET | `/erate/service-providers/{id}` | Get a service provider | Any |
| POST | `/erate/procurement-postings` | Create a competitive bidding posting | ApplicantCoordinator |
| GET | `/erate/procurement-postings` | List postings | Any |
| GET | `/erate/procurement-postings/{id}` | Get a posting | Any |
| POST | `/erate/procurement-postings/{id}/publish` | Publish a posting and open the 28-day bid window | ApplicantCoordinator |
| POST | `/erate/procurement-postings/{id}/close-window` | Close the bid window after it fully elapses | ApplicantCoordinator |
| POST | `/erate/procurement-postings/{id}/cancel` | Cancel a DRAFT or POSTED posting | ApplicantCoordinator |
| POST | `/erate/procurement-postings/{id}/select-winner` | Evaluate qualified bids and award | ApplicantCoordinator, ApplicantCertifier |
| POST | `/erate/bids` | Submit a bid against a posted posting | VendorRepresentative |
| GET | `/erate/bids` | List bids | Any |
| GET | `/erate/bids/{id}` | Get a bid | Any |
| POST | `/erate/bids/{id}/qualify` | Mark a submitted bid as qualified | ApplicantCoordinator |
| POST | `/erate/bids/{id}/disqualify` | Disqualify a submitted or qualified bid | ApplicantCoordinator |
| POST | `/erate/contracts` | Create a draft contract from an awarded posting | ApplicantCoordinator |
| GET | `/erate/contracts` | List contracts | Any |
| GET | `/erate/contracts/{id}` | Get a contract | Any |
| POST | `/erate/contracts/{id}/certify` | Certify a draft contract | ApplicantCertifier |
| POST | `/erate/contracts/{id}/terminate` | Terminate a certified contract | ApplicantCertifier |
| POST | `/erate/funding-requests` | Create a draft funding request | ApplicantCoordinator |
| GET | `/erate/funding-requests` | List funding requests | Any |
| GET | `/erate/funding-requests/{id}` | Get a funding request | Any |
| POST | `/erate/funding-requests/{id}/certify` | Certify and file the request, pinning discount rates | ApplicantCertifier |
| POST | `/erate/funding-requests/{id}/begin-review` | Open PIA review of a filed request | PIAReviewer |
| POST | `/erate/funding-requests/{id}/request-info` | Issue an information request | PIAReviewer |
| POST | `/erate/funding-requests/{id}/pia-responses` | Respond to an information request (OCC-guarded) | ApplicantCoordinator |
| POST | `/erate/funding-requests/{id}/decide` | Issue the funding decision | CommitmentOfficer |
| POST | `/erate/funding-requests/{id}/service-start` | Record that services have started | ApplicantCoordinator |
| POST | `/erate/funding-request-lines` | Add a funding request line | ApplicantCoordinator |
| GET | `/erate/funding-request-lines` | List funding request lines | Any |
| GET | `/erate/funding-request-lines/{id}` | Get a funding request line | Any |
| POST | `/erate/invoice-submissions` | Submit an invoice claim against a committed line | ApplicantCoordinator, VendorRepresentative |
| GET | `/erate/invoice-submissions` | List invoice submissions | Any |
| GET | `/erate/invoice-submissions/{id}` | Get an invoice submission | Any |
| POST | `/erate/invoice-submissions/{id}/begin-review` | Open review of a submitted invoice | InvoiceProcessor |
| POST | `/erate/invoice-submissions/{id}/approve` | Approve an invoice and compute reimbursement | InvoiceProcessor |
| POST | `/erate/invoice-submissions/{id}/pay` | Disburse an approved invoice | InvoiceProcessor |
| POST | `/erate/invoice-submissions/{id}/reject` | Reject an invoice or revoke an un-paid approval | InvoiceProcessor |
| POST | `/erate/invoice-submissions/{id}/resubmit` | Resubmit a rejected invoice | ApplicantCoordinator, VendorRepresentative |
| POST | `/erate/service-substitutions` | Request a service substitution (OCC-guarded) | ApplicantCoordinator |
| GET | `/erate/service-substitutions` | List substitutions | Any |
| GET | `/erate/service-substitutions/{id}` | Get a substitution | Any |
| POST | `/erate/service-substitutions/{id}/approve` | Approve a substitution | ProgramAdmin |
| POST | `/erate/service-substitutions/{id}/deny` | Deny a substitution | ProgramAdmin |
| POST | `/erate/appeals` | File an appeal of a denied funding request | ApplicantCoordinator |
| GET | `/erate/appeals` | List appeals | Any |
| GET | `/erate/appeals/{id}` | Get an appeal | Any |
| POST | `/erate/appeals/{id}/begin-review` | Open appeal review | AppealOfficer |
| POST | `/erate/appeals/{id}/decide` | Decide an appeal | AppealOfficer |
| GET | `/erate/retained-documents` | List retained documents | Any |
| GET | `/erate/retained-documents/{id}` | Get a retained document | Any |
| POST | `/erate/retained-documents/{id}/place-hold` | Place an audit hold on a document | Auditor |
| POST | `/erate/retained-documents/{id}/release-hold` | Release an audit hold | Auditor |
| POST | `/erate/retained-documents/{id}/purge` | Purge a document past its retention horizon | Auditor |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions for each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_APPLICANT_ACCESS_DENIED` | 403 Forbidden |
| `ERR_PROVIDER_ACCESS_DENIED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_CONTRACT_CERTIFIER` | 409 Conflict |
| `ERR_SOD_COMMITMENT_OFFICER` | 409 Conflict |
| `ERR_AUDIT_HOLD_ACTIVE` | 409 Conflict |
| `ERR_BID_WINDOW_CLOSED` | 409 Conflict |
| `ERR_BID_WINDOW_STILL_OPEN` | 409 Conflict |
| `ERR_FILING_WINDOW_CLOSED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_PASSED` | 409 Conflict |
| `ERR_INVOICE_DEADLINE_PASSED` | 409 Conflict |
| `ERR_PRICE_NOT_PRIMARY` | 409 Conflict |
| `ERR_CONTRACT_TERM_OVERLAP` | 409 Conflict |
| `ERR_NO_QUALIFIED_BIDS` | 409 Conflict |
| `ERR_SERVICE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_SUBSTITUTION_CATEGORY_MISMATCH` | 409 Conflict |
| `ERR_APPEAL_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_EMPTY_REQUEST` | 409 Conflict |
| `ERR_CONTRACT_NOT_CERTIFIED` | 409 Conflict |
| `ERR_LINE_NOT_COMMITTED` | 409 Conflict |
| `ERR_SERVICES_NOT_STARTED` | 409 Conflict |
| `ERR_CROSS_ENTITY_MISMATCH` | 409 Conflict |
| `ERR_BID_NOT_AWARDED` | 409 Conflict |
| `ERR_DISCOUNT_SNAPSHOT_MISSING` | 409 Conflict |
| `ERR_CONTRACT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_REIMBURSEMENT_EXCEEDS_REMAINING` | 409 Conflict |
| `ERR_DOCUMENT_NOT_PURGEABLE` | 409 Conflict |
