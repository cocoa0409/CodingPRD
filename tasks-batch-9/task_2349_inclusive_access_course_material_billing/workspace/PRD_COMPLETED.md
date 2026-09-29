# Inclusive Access Course Material Billing API — Product Requirements Document

## 1. Introduction

Inclusive access is the university's answer to a decade of textbook price inflation: instead of sending students to a bookstore shelf, the institution negotiates a discounted per-student price with the publisher, delivers the material inside the learning management system on the first instructional day, and posts the discounted amount directly to the student's bursar account. The bargain only works if it is genuinely optional, so every charge carries a legally mandated opt-out window during which a student may decline the material, lose access, and be refunded in full. This API is the system of record for that bargain end to end — the publisher contract and its enrollment-banded price list, the faculty adoption that binds a title to a course section, the day-one charge posting, the opt-out lifecycle, and the eventual settlement with the publisher.

The hard problem this service solves is that three independent quantities must stay in agreement at all times, and each of them moves for different reasons. The first is money on the bursar account, tracked as an append-only ledger of signed movements. The second is the entitlement count — how many learning-management-system seats the section has actually provisioned. The third is the publisher settlement, which is not a stored total but a computation over the same underlying facts, and which deliberately admits two different answers depending on whether the publisher is paid for enrolled headcount or for the days access actually existed. Opting a student out and letting that student opt back in is a compensating cycle that must leave both money and seats exactly where they started. Changing a title after billing has begun is the opposite: it conserves seats while deliberately rewriting money.

Beyond the ledger, the service carries a compliance obligation. Most states now require the institution to disclose what inclusive access actually saved students relative to publisher list prices, and to file that disclosure by a statutory deadline. The affordability report is therefore a first-class resource with its own certification lifecycle, gated on the publisher reconciliation being current rather than stale — a compliance officer must never certify a savings figure that a mid-flight refund has already invalidated. Every date and time decision in the system reads a logical clock rather than wall time, so that a full academic year can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

The rules in this section apply to every endpoint unless a later section explicitly narrows them. They are contract-level: field names, formats, status codes, header names and enumeration spellings are exact.

### 2.1. Operators, Roles and Resource Ownership

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role the operator is acting in. If either header is absent, or if `X-User-Role` is not one of the six role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the named role is not authorized for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). The authoritative role list per endpoint is the fourth column of the table in §4.

The six roles are `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `Student` and `ComplianceOfficer`. The role model is one of segregation of duties: the operator who authors an adoption may never be the operator who approves it, the office that posts a charge is not the office that files an opt-out, and the officer who certifies a state disclosure has no authority over billing at all.

- When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition asks for it — as `approved_by_user_id` on an `Adoption`, as `computed_by_user_id` and `settled_by_user_id` on a `ReconciliationRun` — but never compares it to any entity's `id`.
- When `X-User-Role` is `Faculty`, `X-User-ID` is likewise an opaque operator identifier, not an entity `id`. It is recorded as `submitted_by_user_id` on an `Adoption`, and it is compared for ownership against the `instructor_user_id` recorded on the `CourseSection` — that string is itself an opaque Faculty operator identifier supplied when the section was created, not a foreign key to any entity.
- When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier. The server does not persist it and does not compare it to any entity's `id`.
- When `X-User-Role` is `BursarOfficer`, `X-User-ID` is an opaque operator identifier. The server records it as `decided_by_user_id` on an `OptOutRequest` when the officer grants or denies it, but does not compare it to any entity's `id`.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier. The server records it as `certified_by_user_id` on a `DisclosureReport`, but does not compare it to any entity's `id`.
- When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` entity. Ownership checks on any resource that references a `Student` compare the resource's foreign-key field to `X-User-ID`.

Ownership is enforced, with `ERR_NOT_RESOURCE_OWNER` (HTTP 403), on exactly these operations: `POST /adoptions` and `POST /adoptions/{adoption_id}/submit` (the acting `Faculty` operator's `X-User-ID` must equal the section's `instructor_user_id`); `POST /opt-out-requests`, `POST /opt-out-requests/{request_id}/rescind` and `POST /opt-out-requests/{request_id}/resubmit` (the acting `Student`'s `X-User-ID` must equal the `student_id` of the charge behind the request); and the three scoped reads `GET /students/{student_id}/ledger-entries`, `GET /charges/{charge_id}` and `GET /charges/{charge_id}/ledger-entries` (a `Student` may only read its own records). A `BursarOfficer` may decide an opt-out but may never file, rescind or re-file one; a `Faculty` operator may author and submit adoptions but may never approve one.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 like every other timestamp this API emits.
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

### 2.3. Pagination and List Filtering

List endpoints are paginated through two query parameters. `limit` caps the number of items returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` is the number of items to skip and defaults to 0. A `limit` or an `offset` that is not an integer, or that falls outside those bounds, is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an empty value for either is treated as absent and falls back to the default. Both are echoed in the `meta` object of the envelope alongside `total_count` (the number of items matching the query before pagination) and `has_more` (true when items remain beyond the current page).

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. Because `created_at` is read from the logical clock, many rows share one timestamp; such ties are broken by creation order, so the row created first sorts first.

Collections also accept exact-match filters, which combine with pagination and with each other. Filter values are compared as strings against the stored field, and any query parameter that is neither a declared filter of the endpoint nor one of the two pagination controls is ignored rather than rejected:

- Terms may be filtered by `code` and by `status`; a term's sections by `ia_status`; a term's disclosure reports by `status`.
- Students may be filtered by `external_id` and `status`; a student's enrollments by `status`; a student's charges by `billing_status`; a student's ledger movements by `entry_type`.
- Agreements may be filtered by `agreement_code`, `status` and `reconciliation_status`; an agreement's titles by `status`; an agreement's reconciliation runs by `term_id` and `status`.
- Titles may be filtered by `agreement_id`, `isbn`, `status` and `format`; pricing tiers by `title_id`.
- Sections may be filtered by `term_id`, `ia_status` and `instructor_user_id`; a section's adoptions by `status`; a section's enrollments by `status` and `registration_type`.
- Adoptions may be filtered by `section_id`, `title_id`, `supersedes_adoption_id` and `status`.
- Enrollments may be filtered by `section_id`, `student_id`, `status` and `registration_type`; an enrollment's charges by `billing_status`.
- Charges may be filtered by `enrollment_id`, `adoption_id`, `student_id`, `billing_status` and `access_status`; a charge's ledger movements by `entry_type`; a charge's opt-out requests by `status`.
- Ledger movements may be filtered by `charge_id`, `student_id`, `entry_type` and `reason_code`.
- Opt-out requests may be filtered by `charge_id`, `status` and `reason_code`.
- Reconciliation runs may be filtered by `agreement_id`, `term_id`, `supersedes_run_id`, `status` and `method`.
- Disclosure reports may be filtered by `term_id`, `reporting_state_code`, `status` and `compliance_status`.

### 2.4. The Logical Clock

Nothing in this system reads wall-clock time. Every deadline comparison, every timestamp stamped onto a resource, and every proration date arithmetic reads a logical clock that any of the six roles may set by supplying a `current_utc` instant. `current_utc` is a required string holding an ISO 8601 instant; a trailing `Z` or an explicit UTC offset is accepted and normalized to UTC, and a value carrying no offset is read as already being UTC. Before the clock has ever been set, its value is `2026-08-01T00:00:00Z`. Setting the clock replaces the logical present for all later requests and mutates no business entity whatsoever; the response is an object whose `data` is `{"current_utc": ...}` echoing the supplied string verbatim, exactly as it was sent rather than reformatted.

Wherever this document says "the current logical date", it means the calendar date of the logical clock instant in UTC; "the current logical instant" means the full timestamp.

### 2.5. Common Resource Properties and the Append-Only Ledger Row

Every resource in this system carries an `id`: a server-minted UUID, with no type prefix and no client control over its value. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock at creation.

All resources except `LedgerEntry` additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that resource — including mutations the server performs on its own initiative as part of a cascade, and including recomputation of derived fields such as counters and rates. `version` is bumped at most once per resource per request: when one request touches the same resource several times — a cascade that flips a status and then recomputes that same entity's counters, for instance — `version` still advances by exactly 1 and `updated_at` is stamped once. A resource whose creating request also advances it through an in-request transition, as a `StudentCharge` does from `PENDING` to `POSTED`, is still returned at `version` 1. A `LedgerEntry` is different: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because a bursar movement is never modified and never deleted once appended. The ledger is strictly append-only; a correction is expressed as an additional, offsetting row.

Each `LedgerEntry` also records `posted_at`, the logical-clock instant at which the movement was appended, and `source_event`, a string naming the API operation that appended it, written as the operation's HTTP method, a space, and the operation's path template — for example `POST /opt-out-requests/{request_id}/grant` for a movement appended by granting an opt-out.

### 2.6. Cents, Ratios and Rounding Discipline

All money in this system is an integer number of cents. There are no fractional cents anywhere, in storage or in a response body. Percentage and rate inputs — `admin_fee_pct`, `bookstore_margin_pct`, `max_list_price_pct`, `rebate_pct` — are exact decimal fractions and are applied as given, never pre-rounded.

Three rounding rules apply throughout and are never varied:

- **Money.** Any money figure produced by a multiplication or a division is rounded half up to whole cents. The single exception is the list-price cap described in §3.5, which is deliberately rounded *down* (any fractional cent is discarded).
- **Ratios.** Any ratio the system stores or reuses — `proration_pct`, `participation_rate`, `savings_pct`, and the access-day weight used in publisher reconciliation — is rounded half up to exactly 4 decimal places. A stored ratio is serialized as a JSON number rather than a fixed-width string, so a ratio of exactly one appears as `1.0` and a zero rate as `0.0`. Where a ratio feeds a later multiplication, the rounding of the ratio happens *first* and the product is rounded second. This order is pinned; rounding only at the end produces different cents and is wrong.
- **Round per line, then sum.** Publisher settlement totals are sums of already-rounded per-charge amounts. The system never sums unrounded values and rounds the total.

Threshold comparisons against these figures are inclusive or exclusive exactly as stated in §3, and the boundary cases are load-bearing: a participation rate of exactly 0.5000 is not below the participation floor, a savings percentage of exactly 0.3000 is compliant, and a request arriving at exactly an opt-out deadline instant is inside the window.

### 2.7. The Two Conserved Quantities

This system defines two named conserved quantities and permits zero drift in either.

**Money on the bursar account.** For every `StudentCharge`, the stored `net_billed_cents` equals the sum of `amount_cents` over every `LedgerEntry` bearing that charge's `charge_id`. For every `Student`, the stored `bursar_balance_cents` equals the sum of `amount_cents` over every `LedgerEntry` bearing that student's `student_id`. A positive `amount_cents` debits the student, a negative one credits the student. Because the ledger includes rebill rows as well as charges and refunds, these two identities hold after every operation without exception, and the permitted drift is zero cents. The compensating-pair form of the invariant matters most: if a charge's ledger sum was some amount before an opt-out was granted, then granting the opt-out and subsequently rescinding it leaves the charge's ledger sum at that same amount and the student's `bursar_balance_cents` unchanged, with exactly two additional rows — a refund of that amount followed by a re-charge of that amount.

**Entitlement seats.** For every `CourseSection` whose `ia_status` is `BILLED` or `AT_RISK`, `provisioned_access_count` plus `revoked_access_count` equals the number of charges on that section whose `access_status` is anything other than `NOT_PROVISIONED`. Permitted drift is zero seats. Two compensating-pair forms follow. First, a title-change rebill repoints charges and rewrites money but must leave `provisioned_access_count` and the section's charge count unchanged — no seat is created or destroyed by changing which book the seat entitles the student to. Second, granting an opt-out (which revokes a seat) and then rescinding it (which restores the seat) returns both `provisioned_access_count` and `revoked_access_count` to their pre-grant values. This quantity is keyed on `access_status` alone; `billing_status` is irrelevant to it.

### 2.8. Parallel State Dimensions

Two entities in this system carry two independent state fields that advance on disjoint triggers, and conflating them is the most common way to get this domain wrong.

A `PublisherAgreement` has a contractual dimension in `status`, valued `DRAFT`, `ACTIVE` or `SUSPENDED`, and a settlement dimension in `reconciliation_status`, valued `NOT_STARTED`, `COMPUTED`, `STALE`, `DISPUTED` or `SETTLED`. Suspending an agreement does not touch its `reconciliation_status`; computing or settling a reconciliation does not touch its `status`. A suspended agreement can still be reconciled and settled, which is precisely what happens when a publisher relationship ends mid-term.

A `StudentCharge` has a money dimension in `billing_status`, valued `PENDING`, `POSTED`, `PARTIALLY_REFUNDED`, `REFUNDED` or `REBILLED`, and a learning-management-system entitlement dimension in `access_status`, valued `NOT_PROVISIONED`, `PROVISIONED`, `REVOKED` or `RESTORED`. Money cycles `POSTED` → `REFUNDED` → `POSTED` as a student opts out and back in, while entitlement cycles `PROVISIONED` → `REVOKED` → `RESTORED` → `REVOKED` over the same events. The two axes advance in the same request but are stored, queried and reported separately. Note that `PENDING` is never observable through any endpoint: it is the pre-ledger instant inside the same request that creates the charge row, and by the time that request returns the charge has already reached `POSTED`.

### 2.9. Cascade Discipline

Several operations in this system are multi-hop: a single request mutates the entity named in the path and then, as a consequence, mutates entities two and three levels away. Cascades are described hop by hop in §3, and the hop ordering is normative — each hop is stated as a consequence of the previous one. Four cascades share a common tail: after an opt-out grant, an opt-out rescind, an enrollment drop, or a title-change rebill, the section's counters and participation rate are recomputed, the section's `ia_status` may flip between `BILLED` and `AT_RISK`, and finally the `reconciliation_status` of the `PublisherAgreement` that prices the affected charge moves from `COMPUTED` or `DISPUTED` to `STALE`.

Derived fields are recomputed, not incrementally patched, whenever anything they depend on changes. `Student.bursar_balance_cents` and `StudentCharge.net_billed_cents` are recomputed from the ledger; `CourseSection.enrolled_count` (the section's enrollments whose `status` is `ENROLLED`), `provisioned_access_count` (its charges whose `access_status` is `PROVISIONED` or `RESTORED`), `revoked_access_count` (its charges whose `access_status` is `REVOKED`), `opted_out_count` (the opt-out requests against its charges whose `status` is currently `GRANTED`, so a rescinded cycle removes one again) and `participation_rate` are recomputed from their underlying rows; `AcademicTerm.ia_section_count` is recomputed from the term's sections carrying `inclusive_access_flag` true. Each such recomputation is a mutation of the entity that owns the field, so it refreshes that entity's `updated_at` and increments its `version` per §2.5.

### 2.10. Stale-Read Protection on Section and Agreement Writes

Two write operations require the client to prove it was looking at a current parent when it composed the request. This is the only concurrency mechanism in the system; no other endpoint accepts a version field, and clients must not send one.

`POST /adoptions` requires a non-optional `expected_section_version` field carrying the client's last observed `version` of the target `CourseSection`. If that value does not equal the section's current `version`, the create is rejected with `ERR_STALE_SECTION_VERSION` (HTTP 412). A second adoption on the same section is legitimate under the product semantics — a new adoption may supersede the section's currently approved one as a title change — so no state precondition can catch this case. The version check is what protects a client that authored its adoption against an outdated view of the section: a different frozen billing basis, a different `ia_status`, or a different set of approved adoptions.

`POST /reconciliation-runs` requires a non-optional `expected_agreement_version` field carrying the client's last observed `version` of the target `PublisherAgreement`. If that value does not equal the agreement's current `version`, the create is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). A newer run legitimately supersedes the prior computed run for the same agreement and term, so a second create would otherwise succeed; the version check rejects a run computed from an outdated view of the agreement — one where a cascade has already flipped `reconciliation_status` to `STALE`, or where the agreement has been suspended, since the client's read.

### 2.11. Identifier Resolution and Validation Precedence

Path identifiers are resolved strictly left to right, and the first one that fails to resolve determines the error. The identifier names used in paths are `term_id`, `student_id`, `agreement_id`, `title_id`, `tier_id`, `section_id`, `adoption_id`, `enrollment_id`, `charge_id`, `entry_id`, `request_id`, `run_id` and `report_id`, and they map to `ERR_TERM_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`, `ERR_TIER_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ADOPTION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_OPT_OUT_REQUEST_NOT_FOUND`, `ERR_RUN_NOT_FOUND` and `ERR_REPORT_NOT_FOUND` respectively, all HTTP 404.

Foreign keys supplied in a request body are resolved after the path and in a fixed declaration order: `term_id`, then `agreement_id`, then `title_id`, then `section_id`, then `student_id`, then `enrollment_id`, then `adoption_id`, then `charge_id`, then `supersedes_adoption_id`, then `supersedes_run_id`. Each unresolved key yields the same 404 identifier as its path counterpart; `supersedes_adoption_id` yields `ERR_ADOPTION_NOT_FOUND` and `supersedes_run_id` yields `ERR_RUN_NOT_FOUND`.

When several checks could fire on one request, they are evaluated in a single global order and the first failure is returned. From highest precedence to lowest:

1. Authentication headers present and the role recognized — `ERR_UNAUTHENTICATED`.
2. The role is authorized for this endpoint — `ERR_ROLE_NOT_PERMITTED`.
3. Request body shape on every write: required fields present, types correct (every string field non-empty, every integer field a true integer rather than a boolean or a fractional number), enum members recognized, numeric ranges respected, the declared orderings between two fields of the same body honoured (a term's `term_end_date` after its `term_start_date`, an agreement's `effective_to` after its `effective_from`, a pricing tier's `max_enrollment` not below its `min_enrollment`), and unknown fields rejected outright — `ERR_INVALID_REQUEST` (HTTP 400). A field supplied as JSON `null` is treated as absent: it falls back to its default where one exists and is reported as missing where the field is required.
4. Path identifiers resolve, left to right — the 404 family above.
5. Body foreign keys resolve, in declaration order — the 404 family above.
6. Ownership, per §2.1 — `ERR_NOT_RESOURCE_OWNER`.
7. Stale-read protection, per §2.10 — `ERR_STALE_SECTION_VERSION` or `ERR_STALE_AGREEMENT_VERSION`.
8. The target entity is in a state from which the requested transition is declared — `ERR_INVALID_STATE` (HTTP 409). Re-running a transition out of a terminal state, acting on a superseded reconciliation run, and acting on a published disclosure report all land here.
9. The term's money gate — `ERR_TERM_BILLING_LOCKED`.
10. The term's workflow gate — `ERR_TERM_NOT_OPEN`.
11. The section's inclusive-access posture gate — `ERR_SECTION_NOT_FLAGGED`.
12. Segregation of duties on adoption approval — `ERR_SEGREGATION_OF_DUTIES`.
13. Reconciliation currency for disclosure certification — `ERR_RECONCILIATION_NOT_CURRENT`.
14. The state filing deadline — `ERR_DISCLOSURE_DEADLINE_PASSED`.
15. Agreement activation readiness — `ERR_AGREEMENT_NOT_ACTIVATABLE`.
16. Title withdrawal safety — `ERR_TITLE_ALREADY_BILLED`.
17. The pricing agreement is active — `ERR_AGREEMENT_NOT_ACTIVE`.
18. The enrollment behind the charge is still enrolled — `ERR_ENROLLMENT_NOT_ACTIVE`.
19. The section has an approved adoption — `ERR_ADOPTION_NOT_APPROVED`.
20. The adopted title is not withdrawn — `ERR_TITLE_WITHDRAWN`.
21. Agreement coverage of the term — `ERR_AGREEMENT_WINDOW_MISMATCH` (HTTP 422).
22. Supersede-target validity — `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 422).
23. The faculty adoption deadline — `ERR_ADOPTION_DEADLINE_PASSED`.
24. The opt-out window — `ERR_OPT_OUT_WINDOW_CLOSED`.
25. The late-registration cutoff — `ERR_LATE_REGISTRATION_CLOSED`.
26. Enrollment and drop date ranges — `ERR_ENROLLMENT_DATE_OUT_OF_RANGE` (HTTP 422).
27. Access-window validity — `ERR_ACCESS_WINDOW_INVALID` (HTTP 422).
28. Pricing band non-overlap — `ERR_TIER_BAND_OVERLAP`.
29. Concurrent-title capacity — `ERR_CONCURRENT_TITLE_LIMIT`.
30. One open opt-out per charge — `ERR_DUPLICATE_OPT_OUT_OPEN`.
31. The opt-out cycle limit — `ERR_OPT_OUT_CYCLE_LIMIT`.
32. Duplicate active enrollment — `ERR_DUPLICATE_ENROLLMENT`.
33. Business-key uniqueness — `ERR_DUPLICATE_RESOURCE_KEY`.
34. A batch posting produces at least one charge — `ERR_NO_BILLABLE_CHARGES` (HTTP 422).
35. A pricing tier covers the tier basis — `ERR_NO_PRICING_TIER` (HTTP 422).
36. A single posting is not a duplicate — `ERR_CHARGE_ALREADY_EXISTS`.
37. Settlement variance within tolerance — `ERR_VARIANCE_TOLERANCE_EXCEEDED`.
38. Dispute variance outside tolerance — `ERR_VARIANCE_WITHIN_TOLERANCE`.
39. The term is locked before settlement — `ERR_TERM_NOT_LOCKED`.

The practical consequence of this ordering is worth stating plainly: a request that is both unauthorized and semantically impossible reports the authorization failure, and a request whose section is stale reports the stale version rather than any later business rule it also violates.

## 3. Business Logic & Workflows

### 3.1. The Academic Term as Calendar and Gate

Everything in this system is scoped to an **AcademicTerm**, which serves two purposes at once: it is the calendar every date rule reads, and it is the master gate that opens and closes the whole program. A `ProgramAdmin` creates a term with a short `code` of between 1 and 16 characters, unique across terms, a human-readable `name`, and the instructional envelope `term_start_date` and `term_end_date` as ISO calendar dates in `YYYY-MM-DD` form, where the end date must be strictly later than the start date. From those two dates the server derives `total_term_days` as the number of days from the start date through the end date inclusive — their difference in days, plus one. That single integer is the denominator of every proration and every access-day weight computed anywhere in this system, so it is worth naming explicitly: a term running from the first of September through the fifteenth of December has a `total_term_days` of 106, not 105. Separately, `instructional_days` — an integer of at least 1 — is the registrar's published count of teaching days; it appears in the disclosure narrative and enters no calculation.

Five further dates define the term's control gates, and each is an ISO calendar date. `census_date` is the official enrollment census, used only by the audit pricing basis described in §3.5. `add_drop_deadline` is the last day of the add/drop period; it both caps the opt-out window and marks the boundary between a full refund and a prorated one on a drop. `late_registration_cutoff_date` is the last day a new enrollment may be created at all. `adoption_deadline_date` is the faculty adoption submission deadline. `disclosure_deadline_date` is the statutory filing deadline for the state textbook cost disclosure. `opt_out_window_days` is optional, must be at least 1, and defaults to 14 — a nominal two-week opt-out window measured from each charge's own posting instant.

A newly created term is `PLANNING`, with `ia_section_count` at 0 and `closed_at` null. A `ProgramAdmin` opens it, moving `PLANNING` → `OPEN`, which is permitted only while the term is `PLANNING`; the transition recomputes `ia_section_count` from the term's sections that carry the inclusive access flag and increments the term's `version`. Section flagging and charge posting both require an `OPEN` term. Creating an enrollment, by contrast, is not gated on the term's status at all — the registrar may register a student while the term is still `PLANNING` or after it has locked or closed — and is constrained only by the date rules of §3.4.

When billing for the term is complete, the same role locks it, moving `OPEN` → `BILLING_LOCKED`, permitted only from `OPEN`, and again incrementing `version`. Locking is the gate into publisher settlement: no reconciliation run may be settled until the term is locked, and a settle attempt against an unlocked term is rejected with `ERR_TERM_NOT_LOCKED`. Locking simultaneously freezes student-facing money: from that point on, batch charge posting, single charge posting, filing an opt-out, rescinding one and re-filing one are all rejected with `ERR_TERM_BILLING_LOCKED`, and the same rejection applies once the term is `CLOSED`. Granting and denying an opt-out remain available to a `BursarOfficer` in a locked term — the bursar must still be able to work through the queue of requests filed before the lock.

`BILLING_LOCKED` → `CLOSED` is never requested directly. The server performs it as the second hop of a settlement cascade (§3.8), and only when the term is `BILLING_LOCKED` and every `PublisherAgreement` that prices at least one charge in this term — traced from the charge to its adoption, from the adoption to its title, and from the title to the agreement that prices it, whatever that charge's own status and whether or not its section carries the inclusive access flag — has a `reconciliation_status` of `SETTLED`. A term in which no charge has ever been posted satisfies that test vacuously and therefore closes on the first settlement against it. Closing stamps `closed_at` from the logical clock, increments the term's `version`, and fires a third hop that publishes the term's certified disclosures (§3.9). `CLOSED` is terminal.

### 3.2. The Publisher Catalog: Agreements, Titles and Enrollment Bands

A **PublisherAgreement** is the negotiated contract that makes discounted pricing possible. A `ProgramAdmin` registers one with the `publisher_name`, an `agreement_code` unique across agreements, and a coverage window given as `effective_from` (inclusive) and `effective_to` (exclusive, and strictly later than `effective_from`). The commercial terms are all captured on the agreement itself. `admin_fee_pct` is the campus administrative fee added on top of the negotiated band price and must lie between 0 and 0.25 inclusive. `bookstore_margin_pct` is the share of each charge the bookstore withholds from the publisher and must lie between 0 and 0.50 inclusive. `price_floor_cents` is the contractual minimum per-student price and must not be negative. `max_list_price_pct` is a hard ceiling on the per-student price expressed as a fraction of the title's list price; it is optional, must be greater than 0 and at most 1, and defaults to 0.60 — sixty percent of list. `rebate_threshold_cents`, which must not be negative, and `rebate_pct`, which must lie between 0 and 0.20 inclusive, define the volume rebate applied at settlement. A new agreement is `DRAFT` in its contractual dimension and `NOT_STARTED` in its settlement dimension, with `settled_amount_cents` and `suspend_reason_note` both null.

Each **CourseMaterialTitle** is registered under exactly one agreement, in a payload carrying that `agreement_id`. A title has an `isbn` that must be unique within its agreement, a printed `title` string, a `list_price_cents` that must be greater than 0 — this is the savings baseline the state disclosure compares against — and a `format` that is either `DIGITAL` or `DIGITAL_PLUS_PRINT`. A new title is `ACTIVE`.

Pricing lives one level deeper, as **PricingTier** rows attached to a title. Each band declares `min_enrollment`, an inclusive lower bound of at least 1, an optional `max_enrollment` that is an inclusive upper bound and, when omitted or null, means the band is unbounded above, and the `per_student_price_cents` negotiated for that band, which must be greater than 0. When `max_enrollment` is supplied it must not be smaller than `min_enrollment`. Bands of one title may never overlap: a candidate band is rejected with `ERR_TIER_BAND_OVERLAP` when the candidate's lower bound is less than or equal to an existing band's upper bound *and* that existing band's lower bound is less than or equal to the candidate's upper bound, treating a null upper bound as unbounded on either side. Adjacency is legal and is in fact the intended pattern — a band starting exactly one above an existing band's upper bound does not overlap it.

Activation is the readiness gate on the catalog. Moving an agreement `DRAFT` → `ACTIVE` is permitted only while it is `DRAFT`, and only if the agreement has at least one title in `ACTIVE` status and every one of its `ACTIVE` titles carries at least one pricing band. A catalog that fails either half of that test is rejected with `ERR_AGREEMENT_NOT_ACTIVATABLE`; a successful activation increments the agreement's `version`.

Suspension is the exit. Moving `ACTIVE` → `SUSPENDED` is permitted only from `ACTIVE`, requires a `suspend_reason_note`, which is stored on the agreement, and increments `version`. It deliberately leaves `reconciliation_status` untouched. From the moment an agreement is suspended, three operations touching any of its titles are rejected with `ERR_AGREEMENT_NOT_ACTIVE`: approving an adoption of one of its titles, flagging a section for inclusive access under one of its titles, and posting charges — whether the batch form or the single-enrollment form — on a section priced by one of its titles. `SUSPENDED` is terminal in the contractual dimension; an agreement never returns to `ACTIVE`.

A title may be retired from the catalog by moving it `ACTIVE` → `WITHDRAWN`, which is permitted only while the title is `ACTIVE` and only if no approved adoption of that title sits on a section whose `ia_status` is `BILLED` or `AT_RISK`. A title students have already been charged for cannot be withdrawn — it must be replaced through a superseding adoption instead — and an attempt is rejected with `ERR_TITLE_ALREADY_BILLED`. Withdrawal increments the title's `version`, and from then on both adoption approval and section flagging touching that title are rejected with `ERR_TITLE_WITHDRAWN`. `WITHDRAWN` is terminal.

### 3.3. Faculty Adoption: Authoring, Review and Approval

A **CourseSection** is created by a `Registrar` or a `ProgramAdmin` against a term, with a payload naming the `term_id`, the `subject_code` (for example `ECON`), the `catalog_number` (for example `101`) and the `section_number`, which must be unique for the combination of term, subject code and catalog number. The section also names the `instructor_user_id` — the opaque `Faculty` operator identifier that owns adoption authoring for this section — and optionally `max_concurrent_titles`, an integer of at least 1 that defaults to 2 and caps how many approved access windows may cover any single calendar date. A new section is `NOT_FLAGGED` with `inclusive_access_flag` false, every counter (`enrolled_count`, `provisioned_access_count`, `revoked_access_count`, `opted_out_count`) at 0, `participation_rate` at 0.0000, and both `billing_basis_enrollment_count` and `first_posted_at` null.

An **Adoption** is the junction between a section and a title: it is what says "this section delivers this book on day one". A `Faculty` operator authors one in a payload carrying the `section_id`, the `title_id`, the access window as `access_start_date` (inclusive) and `access_end_date` (exclusive), the `expected_section_version` required by §2.10, and optionally a `supersedes_adoption_id` naming the approved adoption this one replaces. A new adoption is `DRAFT` with `revision_count` at 0 and `requires_rebill` false; `submitted_by_user_id`, `approved_by_user_id`, `submitted_at`, `approved_at`, `locked_list_price_cents` and `change_note` are all null at this point. The access window is validated as a half-open interval inside the term: `access_end_date` must be strictly later than `access_start_date`, `access_start_date` must not be earlier than the term's `term_start_date`, and `access_end_date` must not be later than the day after the term's `term_end_date`. A window failing any of those three tests is rejected with `ERR_ACCESS_WINDOW_INVALID`. When `supersedes_adoption_id` is supplied it must reference an adoption on the same section that is currently `APPROVED` and whose `title_id` differs from the candidate's — pointing at another section, at a non-approved adoption, or at the same title is rejected with `ERR_SUPERSEDE_TARGET_INVALID`.

Submission moves an adoption `DRAFT` → `SUBMITTED`. Only the `Faculty` operator whose `X-User-ID` equals the section's `instructor_user_id` may submit, the term must be either `PLANNING` or `OPEN`, and — for an original adoption, meaning one whose `supersedes_adoption_id` is null — the current logical date must be on or before the term's `adoption_deadline_date`, with a later submission rejected as `ERR_ADOPTION_DEADLINE_PASSED`. A superseding adoption is deliberately exempt from that deadline: the late title change is a sanctioned business path, not an exception to be worked around. Submission stamps `submitted_by_user_id` from the submitting operator's `X-User-ID` and `submitted_at` from the logical clock.

A `ProgramAdmin` reviewing a submitted adoption may return it for revision, moving `SUBMITTED` → `CHANGE_REQUESTED` with a `change_note` that is stored on the adoption. This is permitted only from `SUBMITTED`. The instructor then resubmits, moving `CHANGE_REQUESTED` → `SUBMITTED`; that transition is permitted only from `CHANGE_REQUESTED`, is again restricted to the owning instructor, and again enforces the adoption deadline for an original adoption while exempting a superseding one. Resubmission increments `revision_count` by 1, refreshes `submitted_at` to the current logical instant, and keeps `submitted_by_user_id` at the identifier of the operator who resubmitted. The revision loop `SUBMITTED` → `CHANGE_REQUESTED` → `SUBMITTED` may run any number of times.

Approval, moving `SUBMITTED` → `APPROVED`, is the most heavily guarded transition in the system. It is a `ProgramAdmin` action and requires all of the following: the adoption is `SUBMITTED`; the approving operator's `X-User-ID` differs from the adoption's `submitted_by_user_id`, since the operator who submitted an adoption may never approve it and an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`; the term is `PLANNING` or `OPEN`, else `ERR_TERM_NOT_OPEN`; the adopted title is `ACTIVE`, else `ERR_TITLE_WITHDRAWN`; the agreement pricing that title is `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE`; that agreement's coverage brackets the whole term, meaning `effective_from` is on or before the term's `term_start_date` and `effective_to` is strictly after the term's `term_end_date`, else `ERR_AGREEMENT_WINDOW_MISMATCH`; the adopted title carries at least one pricing band, else `ERR_NO_PRICING_TIER` — note that no enrollment count exists yet at approval time, so approval only checks that *some* band exists, not that a band covers a particular count; and concurrent-title capacity holds.

Concurrent-title capacity deserves its own statement, because it is a per-date test rather than a per-adoption one. For every calendar date in the candidate's half-open window — from `access_start_date` inclusive up to but excluding `access_end_date` — the system counts the approved adoptions on that section whose own half-open window contains that date, including the candidate being approved. If that count exceeds the section's `max_concurrent_titles` on any single date, the approval is rejected with `ERR_CONCURRENT_TITLE_LIMIT`. Windows that merely touch do not overlap: an earlier adoption whose `access_end_date` equals a later adoption's `access_start_date` contributes nothing to the later window's count.

A successful approval pins `locked_list_price_cents` to the title's current `list_price_cents`, freezing the disclosure savings baseline against later publisher price changes, and stamps `approved_by_user_id` from the approving operator and `approved_at` from the logical clock. If the adoption carries a `supersedes_adoption_id`, approval additionally drives the four-hop title-change cascade described in §3.7.

Finally, an approved adoption may be withdrawn, moving `APPROVED` → `WITHDRAWN`, but only while the section's `ia_status` is `NOT_FLAGGED` or `FLAGGED` — that is, only while no charge has ever posted on the section. If withdrawing leaves the section with no approved adoption at all, the server clears the section's `inclusive_access_flag` to false, returns its `ia_status` to `NOT_FLAGGED`, and recomputes the term's `ia_section_count`. Both `WITHDRAWN` and `SUPERSEDED` are terminal adoption states.

### 3.4. The Roster: Students, Enrollments and Registration Timing

A `Registrar` creates each **Student** with an `external_id` — the registrar's student number, unique across students — a `full_name`, a campus `email` and an academic `program_code`; all four are required non-empty strings stored exactly as supplied, and `email` carries no format check beyond being a string. A new student is `ACTIVE` (the alternative value is `INACTIVE`) with `bursar_balance_cents` at 0. That balance is never written directly; per §2.7 it is always the signed sum of the student's ledger movements.

An **Enrollment** ties a student to a section. The `Registrar` supplies the `section_id`, the `student_id` and the registration date `enrolled_on`. Two date rules apply. First, `enrolled_on` must not be earlier than thirty days before the term's `term_start_date`, and on a later drop the supplied `dropped_on` must not be earlier than the enrollment's `enrolled_on`; either violation is rejected with `ERR_ENROLLMENT_DATE_OUT_OF_RANGE`. Second, `enrolled_on` must be on or before the term's `late_registration_cutoff_date`; a registration attempt past that date is rejected with `ERR_LATE_REGISTRATION_CLOSED`. At most one enrollment with status `ENROLLED` may exist for any given pair of section and student, and a duplicate is rejected with `ERR_DUPLICATE_ENROLLMENT` — a student who dropped and re-registers is fine, because the dropped row no longer occupies the slot.

The server derives `registration_type` from the registration date against the add/drop boundary: it is `REGULAR` when `enrolled_on` is on or before the term's `add_drop_deadline`, and `LATE` otherwise. That single derived value is what later drives proration, and it is why the same book can cost two students different amounts in the same section. Creating an enrollment sets `status` to `ENROLLED` with `dropped_on` null, then recomputes the section's `enrolled_count` and `participation_rate`.

Business keys are enforced across this and the preceding subsections with a single rejection code, `ERR_DUPLICATE_RESOURCE_KEY`: a term's `code`, an agreement's `agreement_code`, a student's `external_id`, the pairing of agreement and `isbn` on a title, the four-part pairing of term, subject code, catalog number and section number on a section, and the pairing of term and `reporting_state_code` on a disclosure report must each be unique.

### 3.5. Day-One Delivery: Flagging, Pricing and Charge Posting

Flagging is the moment a section formally enters the inclusive access program. A `ProgramAdmin` moves the section `NOT_FLAGGED` → `FLAGGED`, which requires that the section is currently `NOT_FLAGGED`, that at least one adoption on it is `APPROVED` (else `ERR_ADOPTION_NOT_APPROVED`), that for every such approved adoption the adopted title is `ACTIVE` (else `ERR_TITLE_WITHDRAWN`) and the agreement pricing that title is `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`), and that the term is `OPEN` (else `ERR_TERM_NOT_OPEN`). Flagging sets `inclusive_access_flag` to true, recomputes the term's `ia_section_count`, and increments the section's `version`.

Charge posting comes in two shapes that share all of their pricing logic. Both read the section's *currently approved adoption*, which means — when more than one adoption on the section stands `APPROVED`, as the concurrent-title allowance permits — the one whose `approved_at` is latest, ties broken by creation order. The batch form, available to a `BursarOfficer` or a `ProgramAdmin`, sweeps the whole section on day one: it creates one charge for every enrolled student who does not yet carry a charge on that adoption, applying the same live-charge test the single form uses below, and processing them in order of the enrollment's `enrolled_on` ascending with ties broken by the student's `external_id` ascending. It answers with `201`, `response_type` `array` and `data` holding the created charge rows in that same posting order, with no pagination fields in `meta`. If no such uncharged enrolled student exists — because every enrolled student is already charged, or because the section has no enrolled student at all — the request is rejected with `ERR_NO_BILLABLE_CHARGES`; that test precedes the band resolution, so an empty sweep reports `ERR_NO_BILLABLE_CHARGES` even when no pricing band would have covered the tier basis either. The single form, available to the same two roles, posts exactly one charge for one named enrollment and is the normal path for a late registrant; it is rejected with `ERR_CHARGE_ALREADY_EXISTS` when that enrollment already carries a charge on the section's currently approved adoption whose `billing_status` is any of `POSTED`, `PARTIALLY_REFUNDED`, `REFUNDED` or `REBILLED`, and rejected with `ERR_ENROLLMENT_NOT_ACTIVE` when the enrollment has been dropped. Both forms require the section's `ia_status` to be `FLAGGED` or `BILLED` (else `ERR_SECTION_NOT_FLAGGED`), at least one approved adoption on the section (else `ERR_ADOPTION_NOT_APPROVED`), an `ACTIVE` pricing agreement (else `ERR_AGREEMENT_NOT_ACTIVE`), and an `OPEN` term (else `ERR_TERM_BILLING_LOCKED`).

Each **StudentCharge** row records the `enrollment_id` it bills, the `adoption_id` whose title is being billed, and the `student_id` that owns the bursar charge as a denormalized convenience for the bursar's own reporting.

**Per-student price.** The negotiated price is resolved in three steps, and the order is fixed. Step one establishes the tier basis, a single enrollment count called *n*: if the section's `billing_basis_enrollment_count` is already set, *n* is that frozen number; otherwise *n* is the section's live `enrolled_count` as observed in this request. Step two selects the pricing band: among the bands of the adopted title, the system finds the one band whose `min_enrollment` is less than or equal to *n* and whose `max_enrollment` is either null or greater than or equal to *n*. Because bands never overlap, at most one band can match; if none matches, the posting is rejected with `ERR_NO_PRICING_TIER` (HTTP 422). Step three layers the commercial terms on the band's `per_student_price_cents`. The band price is multiplied by one plus the agreement's `admin_fee_pct` and the product is rounded half up to whole cents, giving the fee-inclusive price. Independently, a list-price cap is formed by multiplying the title's `list_price_cents` by the agreement's `max_list_price_pct` and discarding any fractional cent — rounding down, not half up. The system then takes the lesser of the fee-inclusive price and the list-price cap, and finally takes the greater of that result and the agreement's `price_floor_cents`. The floor is applied last and therefore wins: a contractual floor set above the list-price cap raises the price above the cap. The outcome is stored as `gross_price_cents`. Dropped enrollments never count toward *n*.

**Proration.** A charge's `proration_pct` is 1.0000 whenever the enrollment's `enrolled_on` is on or before the term's `add_drop_deadline` — a regular registration pays for the whole term. For a late registration, the system counts the elapsed days from the term's `term_start_date` to `enrolled_on`, which is 0 for a student registering on the first instructional day, subtracts that elapsed count from `total_term_days` to get the remaining days, divides the remaining days by `total_term_days`, and rounds that ratio half up to 4 decimal places. The rounding order is pinned: the ratio is rounded to four decimals *first*, then `gross_price_cents` is multiplied by the rounded ratio, and only that product is rounded half up to whole cents to give `billed_amount_cents`.

**The opt-out deadline.** Each charge gets its own `opt_out_deadline_at`, computed from three candidate instants. The nominal window end is the charge's `posted_at` advanced by the term's `opt_out_window_days` days. The add/drop cap is the term's `add_drop_deadline` at 23:59:59.999Z. The minimum-window floor is `posted_at` advanced by five days. The system first takes the earlier of the nominal window end and the add/drop cap, then takes the later of that intermediate result and the minimum-window floor. Two consequences follow directly. When a nominal two-week window would run past the add/drop deadline and more than five days still remain, the add/drop end-of-day instant binds. When the charge posts on or after the add/drop deadline — the ordinary situation for a late registrant — the five-day floor is later than both other candidates and binds instead, guaranteeing every student at least five days to decline the material no matter how late the charge lands. A request arriving at an instant exactly equal to `opt_out_deadline_at` is inside the window and accepted.

**Posting itself.** A charge row is born `PENDING` in its money dimension and `NOT_PROVISIONED` in its entitlement dimension, and both advance inside the very same request. `PENDING` → `POSTED` requires that `gross_price_cents` resolved against a matching band and that `billed_amount_cents` is not negative. On that transition the server appends a `CHARGE` ledger movement whose `amount_cents` equals `billed_amount_cents`, carrying `reason_code` `INITIAL_POST` for a batch posting and `LATE_REGISTRATION_POST` for a single posting of a late-registered enrollment (a single posting of a regular registration also carries `INITIAL_POST`); stamps `posted_at` from the logical clock; computes `opt_out_deadline_at`; advances `access_status` `NOT_PROVISIONED` → `PROVISIONED` and stamps `access_start_at`, which increments the section's `provisioned_access_count`; and recomputes the owning student's `bursar_balance_cents`. On the section's *first* successful posting the section moves `FLAGGED` → `BILLED`, which freezes `billing_basis_enrollment_count` to the `enrolled_count` observed in that request, stamps `first_posted_at`, recomputes `provisioned_access_count`, `revoked_access_count` and `participation_rate`, and increments the section's `version`. That freeze is the single most consequential act in the billing flow: every later charge on the section, and every rebill, prices against the frozen basis, so a section that grows or shrinks after day one never slides into a different pricing band.

Each charge also tracks `refunded_amount_cents`, which starts at 0 and accumulates the absolute value of refunds applied to it, and `rebill_count`, which starts at 0 and counts title-change rebills. `net_billed_cents` is always the signed sum of the charge's ledger movements, and `publisher_share_cents` is that net amount multiplied by one minus the agreement's `bookstore_margin_pct`, rounded half up to whole cents. The publisher share is recomputed on every event that changes the net: initial posting, opt-out grant, opt-out rescind, drop refund and title-change rebill. Two further entitlement timestamps, `access_revoked_at` and `access_restored_at`, stay null until the first revocation and the first restoration respectively.

**Participation.** After any event that moves a section's `provisioned_access_count` or `enrolled_count` — posting, opt-out grant, opt-out rescind, enrollment drop, title-change rebill — the section's `participation_rate` is recomputed as `provisioned_access_count` divided by `enrolled_count`, rounded half up to 4 decimal places, or as 0.0000 when `enrolled_count` is zero. The section's posture then reacts, but only from the two billed postures: a section that is `BILLED` moves to `AT_RISK` when the recomputed rate is strictly below one half (0.5000), and a section that is `AT_RISK` returns to `BILLED` when the recomputed rate is at or above one half. A rate of exactly 0.5000 therefore stays `BILLED`. Each such flip increments the section's `version` and, as its own consequent hop, moves the pricing agreement's `reconciliation_status` from `COMPUTED` or `DISPUTED` to `STALE`.

**The billing summary read.** A `ProgramAdmin`, `BursarOfficer` or `ComplianceOfficer` may pull a purely derived, no-mutation summary of a section that exposes both valid tier bases side by side. It returns the `section_id`, the `ia_status`, the frozen `billing_basis_enrollment_count`, `tier_basis_posting_count` (the production basis — the frozen count actually used for pricing), `tier_basis_census_count` (the audit basis — the number of enrollments on the section whose `enrolled_on` is on or before the term's `census_date` and which are either still `ENROLLED` or whose `dropped_on` is later than the census date), `gross_per_student_posting_cents` and `gross_per_student_census_cents` (the per-student price the three-step pricing rule yields under each of those two bases, each returned as null — never as an error — when the section has no approved adoption or when no pricing band of that adoption's title covers that particular basis), `charge_count`, `posted_charge_count`, `refunded_charge_count`, `total_net_billed_cents`, `total_publisher_share_cents`, `provisioned_access_count`, `revoked_access_count` and `participation_rate`. `tier_basis_posting_count` is the frozen `billing_basis_enrollment_count` when one has been frozen and the live `enrolled_count` before that. The four rollups span every charge of the section whatever its `billing_status`: `charge_count` counts them all, while `posted_charge_count` counts only those sitting exactly at `POSTED` (a `REBILLED` charge is not one of them) and `refunded_charge_count` only those sitting exactly at `REFUNDED` (a `PARTIALLY_REFUNDED` charge is not one of them), and `total_net_billed_cents` and `total_publisher_share_cents` sum `net_billed_cents` and `publisher_share_cents` over all of them. The census basis exists precisely so an auditor can see what a section that crossed a band boundary between day one and the census date *would* have cost — identical stored data, a different band, a different per-student price.

### 3.6. The Opt-Out Window: Grant, Deny, Rescind and Re-file

Opting out is the student's statutory right, and it is a student-only action. A `Student` files an **OptOutRequest** against a posted charge with a payload carrying the `charge_id` and a `reason_code` drawn from `OWNS_COPY`, `COST`, `ALTERNATE_SOURCE` or `OTHER`. The request is born `SUBMITTED` with `cycle_count` at 0, `submitted_at` stamped from the logical clock, and `decided_at`, `decided_by_user_id`, `denial_note` and `rescinded_at` all null, `refund_amount_cents` and `recharge_amount_cents` both 0. At most one request whose `status` is `SUBMITTED` or `GRANTED` may exist per charge at any time, and a second one is rejected with `ERR_DUPLICATE_OPT_OUT_OPEN`. Filing also requires the enrollment behind the charge to still be `ENROLLED` (else `ERR_ENROLLMENT_NOT_ACTIVE`), the current logical instant to be at or before the charge's `opt_out_deadline_at` (else `ERR_OPT_OUT_WINDOW_CLOSED`), and the term to be `OPEN` (else `ERR_TERM_BILLING_LOCKED`). Filing applies no test of its own to the charge's `billing_status`; that gate lives on the grant.

Granting is a `BursarOfficer` decision moving `SUBMITTED` → `GRANTED`. It requires the request to be `SUBMITTED`, then the term to be `OPEN` or `BILLING_LOCKED`, then the enrollment to be `ENROLLED`, then the current logical instant to be at or before the charge's `opt_out_deadline_at`, and last of all — after every one of those — the charge's `billing_status` to be `POSTED` or `REBILLED`. Both the term gate and that final billing-state gate report `ERR_INVALID_STATE` (HTTP 409), the term one in particular rather than `ERR_TERM_BILLING_LOCKED`. The grant records `refund_amount_cents` as the charge's `net_billed_cents` observed *before* any refund is applied, together with `decided_at` and `decided_by_user_id`. Then three hops fire in order. Hop one refunds the charge and revokes its access: `billing_status` moves to `REFUNDED` from either `POSTED` or `REBILLED`, `refunded_amount_cents` takes on (or, from `REBILLED`, grows by) the pre-refund net, a `REFUND` ledger movement with `reason_code` `OPT_OUT_REFUND` is appended for the negative of that amount so the charge's `net_billed_cents` becomes 0, `access_status` moves from `PROVISIONED` or `RESTORED` to `REVOKED` with `access_revoked_at` stamped and the learning-management-system entitlement withdrawn, and the student's `bursar_balance_cents` is recomputed. Hop two, a consequence of that revocation, recomputes the section's `provisioned_access_count` (down by one), `revoked_access_count` (up by one), `opted_out_count` and `participation_rate`, and flips the section `BILLED` → `AT_RISK` if the recomputed rate fell below one half. Hop three, a consequence of the section's billable population having changed, moves the pricing agreement's `reconciliation_status` from `COMPUTED` or `DISPUTED` to `STALE`.

Denial is the other `BursarOfficer` decision, moving `SUBMITTED` → `DENIED` with a `denial_note` stored alongside `decided_at` and `decided_by_user_id`. Denial is deliberately inert: no ledger movement is appended, no access changes, and no section counter moves. It is also gate-free beyond the request being `SUBMITTED` — no term-status test, no enrollment test and no opt-out-window test applies — so the bursar can still clear a queued request after the window has closed or the student has dropped. `DENIED` is terminal.

Rescinding is the compensating action, and it belongs to the student, not the bursar. A `Student` moves a granted request `GRANTED` → `RESCINDED`, which requires the request to be `GRANTED`, the acting `X-User-ID` to equal the charge's `student_id`, the enrollment to still be `ENROLLED`, the current logical instant to be at or before the charge's `opt_out_deadline_at`, and the term to be `OPEN`. It records `recharge_amount_cents` as the absolute value of the most recent `OPT_OUT_REFUND` movement on that charge, and stamps `rescinded_at`. Hop one returns the charge to `POSTED` by appending a `CHARGE` ledger movement with `reason_code` `OPT_IN_RECHARGE` for exactly that absolute amount, so `refunded_amount_cents` returns to 0 and `net_billed_cents` returns to its pre-refund value, and moves `access_status` `REVOKED` → `RESTORED` with `access_restored_at` stamped, incrementing the section's `provisioned_access_count` and decrementing `revoked_access_count`. Hop two recomputes the section's counters and `participation_rate` and flips the section `AT_RISK` → `BILLED` when the recomputed rate is at or above one half. Hop three moves the pricing agreement's `reconciliation_status` from `COMPUTED` or `DISPUTED` to `STALE`. Both conserved quantities of §2.7 are back at their pre-grant values when this completes, with exactly two extra ledger rows on the charge.

A rescinded request may be re-filed. A `Student` moves it `RESCINDED` → `SUBMITTED`, supplying a fresh `reason_code`; this requires the acting `X-User-ID` to equal the charge's `student_id`, the enrollment to be `ENROLLED`, the current logical instant to be at or before the charge's `opt_out_deadline_at`, the term to be `OPEN`, and `cycle_count` to be strictly less than two. Re-filing increments `cycle_count` by 1, refreshes `submitted_at` and the stored `reason_code`, and clears `decided_at` and `decided_by_user_id`; `refund_amount_cents`, `recharge_amount_cents` and `rescinded_at` keep the values the previous cycle left on them. The one-open-request-per-charge rule is tested only when a request is first filed and is not re-tested here. No money moves — the re-charge already happened on the rescind. The full cycle `SUBMITTED` → `GRANTED` → `RESCINDED` → `SUBMITTED` may therefore run at most twice, and a third attempt is rejected with `ERR_OPT_OUT_CYCLE_LIMIT`. Across the whole opt-out lifecycle, a request whose enrollment has been dropped is frozen: filing, granting, rescinding and re-filing on such a charge are all rejected with `ERR_ENROLLMENT_NOT_ACTIVE`, and all four operations are equally subject to `ERR_OPT_OUT_WINDOW_CLOSED` once the charge's deadline instant has passed.

### 3.7. Two Ways Money Changes After Day One: Drops and Title Changes

**The drop.** A `Registrar` drops an enrollment by supplying `dropped_on`, moving it `ENROLLED` → `DROPPED`. The enrollment must currently be `ENROLLED` and the term must be `OPEN` or `BILLING_LOCKED` — either failure is reported as `ERR_INVALID_STATE` (HTTP 409), the enrollment state tested before the term state — and only then is `dropped_on` checked for not being earlier than `enrolled_on`. The refund is computed per charge, the enrollment's participating charges being processed in `created_at` ascending order with ties broken by the owning student's `external_id` ascending: if `dropped_on` is on or before the term's `add_drop_deadline`, the refund is the charge's full `net_billed_cents` — a clean reversal. Otherwise the system computes a retained share by counting the days from the term's `term_start_date` to `dropped_on`, dividing by `total_term_days` and rounding half up to 4 decimal places; multiplies the charge's `net_billed_cents` by one minus that rounded retained share; rounds half up to whole cents; and caps the result at `net_billed_cents` so the institution never over-refunds. As with proration, the ratio is rounded to four decimals before the multiplication, not after. Only charges whose `billing_status` is `POSTED` or `REBILLED` participate; charges already `REFUNDED` or `PARTIALLY_REFUNDED` are skipped entirely.

The resulting `billing_status` follows the refund amount: a refund exactly equal to `net_billed_cents` yields `REFUNDED`, a refund greater than zero but smaller than `net_billed_cents` yields `PARTIALLY_REFUNDED`, and a refund of zero leaves the charge `POSTED` untouched. Note that `PARTIALLY_REFUNDED` is terminal in the money dimension. The drop then cascades in four hops. Hop one applies the refund to each participating charge, growing `refunded_amount_cents`, setting the new `billing_status`, moving `access_status` to `REVOKED` and stamping `access_revoked_at`. Hop two, because a charge was refunded, appends a `REFUND` ledger movement with `reason_code` `DROP_PRORATION` and recomputes the charge's `net_billed_cents` and the student's `bursar_balance_cents`. Hop three, because access was revoked, recomputes the section's `enrolled_count`, `provisioned_access_count`, `revoked_access_count` and `participation_rate`, flipping the section `BILLED` → `AT_RISK` when the recomputed rate falls below one half. Hop four, because the section's billed population changed, moves the pricing agreement's `reconciliation_status` from `COMPUTED` or `DISPUTED` to `STALE` — but only for agreements pricing a charge that actually took a refund in hop one, so dropping an enrollment that carried no participating charge recomputes the section and leaves every agreement's `reconciliation_status` untouched. A charge refunded through a drop can never come back: the rescind path requires an `ENROLLED` enrollment, so a `REFUNDED` charge on a dropped enrollment stays refunded forever.

**The title change.** When a publisher pulls an edition or a department changes its book after billing has begun, the instructor authors a new adoption naming the currently approved one in `supersedes_adoption_id`, and approval of that superseding adoption drives a four-hop rebill on top of everything §3.3 already describes. Hop one moves the superseded adoption `APPROVED` → `SUPERSEDED`, permitted only when that adoption is `APPROVED`, the approving adoption's `supersedes_adoption_id` names it, both sit on the same section, and the two still carry different titles; a target that fails any of those tests at approval time — a target already superseded or withdrawn since authoring, for instance — is rejected with `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 422). `SUPERSEDED` is terminal, and charges are repointed away from it in the next hop.

Hop two is the rebill proper, and it processes the superseded adoption's charges in a fixed order: by the charge's `created_at` ascending, with ties broken by the owning student's `external_id` ascending. Only charges whose `billing_status` is `POSTED` or `REBILLED` participate; `PARTIALLY_REFUNDED` and `REFUNDED` charges are excluded and keep pointing at the superseded adoption. The new title's per-student gross is resolved once for the whole rebill, before any ledger row is appended, so that a missing band cannot leave the rebill half applied: if no pricing band of the new title covers the section's frozen basis, the approval is rejected with `ERR_NO_PRICING_TIER` (HTTP 422). For each participating charge the system captures the current `net_billed_cents`, appends a `REBILL_CREDIT` ledger movement with `reason_code` `TITLE_CHANGE_REBILL` for the negative of that amount, then prices the new title using the three-step rule of §3.5 against the section's frozen `billing_basis_enrollment_count` — never the live `enrolled_count` — and multiplies the resulting new gross by the charge's existing `proration_pct`, which is preserved untouched, rounding half up to whole cents. It appends a `REBILL_CHARGE` movement with `reason_code` `TITLE_CHANGE_REBILL` for the positive of that new amount, repoints the charge's `adoption_id` to the superseding adoption, overwrites `gross_price_cents` and `billed_amount_cents`, sets `billing_status` to `REBILLED`, and increments `rebill_count` by 1. `access_status` is deliberately not touched — the seat is conserved even though the money is not. On the superseding adoption, `requires_rebill` is set to true whenever at least one charge was rebilled this way.

Hop three, because charge amounts changed, recomputes the section's `provisioned_access_count`, `revoked_access_count` and `participation_rate` and recomputes `bursar_balance_cents` for every affected student. Hop four, because the section's billed amounts changed, moves the `reconciliation_status` of both the agreement pricing the superseded title and the agreement pricing the new one — the same agreement in the ordinary case, two distinct ones when the title change crosses publishers — from `COMPUTED` or `DISPUTED` to `STALE`. Hops three and four fire on every approval that carries a `supersedes_adoption_id`, including one where the superseded adoption had no participating charge at all and `requires_rebill` therefore stays false. Taken together, a title change is the precise mirror image of an opt-out cycle: the opt-out cycle conserves money and seats, while the rebill conserves seats and intentionally does not conserve money.

### 3.8. Publisher Reconciliation and Settlement

Reconciliation is where the campus and the publisher compare notes. A `ProgramAdmin` computes a **ReconciliationRun** for exactly one pairing of agreement and term, supplying the `agreement_id`, the `term_id`, the `method`, the publisher's own figures as `publisher_reported_count` (at least 0) and `publisher_reported_amount_cents` (at least 0), the `expected_agreement_version` required by §2.10, and optionally a `supersedes_run_id`. The run is born `COMPUTED` and stamps `computed_by_user_id` from the acting operator; `settled_by_user_id`, `settled_at` and `dispute_note` are null. Creating a run requires the agreement's contractual `status` to be `ACTIVE` or `SUSPENDED`, and its `reconciliation_status` to be `NOT_STARTED`, `STALE` or `COMPUTED`. From `NOT_STARTED` or from `STALE`, the agreement's `reconciliation_status` moves to `COMPUTED`; from `COMPUTED` it stays `COMPUTED`, but only when the new run's `supersedes_run_id` names the agreement-and-term pairing's current computed run, meaning the most recently created run of that pairing whose `status` is `COMPUTED` — a recompute under a different `method`, or against a corrected publisher invoice, replaces the current run without leaving `COMPUTED`. A `supersedes_run_id` that resolves to a run belonging to another agreement or term, to a run that is not `COMPUTED`, or to a run that is no longer the pairing's current computed one is rejected with `ERR_INVALID_STATE` (HTTP 409); `ERR_SUPERSEDE_TARGET_INVALID` is reserved for the adoption path. In every superseding case the named prior run moves `COMPUTED` → `SUPERSEDED`, which appends no ledger movement and freezes that run's stored figures for audit. Each of these paths increments the agreement's `version`. `SUPERSEDED` is terminal, and any attempt to act on a superseded run is rejected with `ERR_INVALID_STATE`.

**Scope and order.** A run's scope is every charge that is priced by a title of the run's agreement — traced from the charge's `adoption_id` to that adoption's `title_id` and from the title to its `agreement_id` — and whose enrollment's section belongs to the run's term and carries `inclusive_access_flag` true. Charges are processed by `created_at` ascending with ties broken by the owning student's `external_id` ascending.

**The count that does not depend on method.** `opted_out_count` on the run is the number of in-scope charges whose `billing_status` is `REFUNDED` and against which at least one opt-out request has reached `GRANTED`. It is computed identically under both methods.

**Method `ENROLLMENT_SNAPSHOT`.** The included set is every in-scope charge whose `billing_status` is `POSTED`, `PARTIALLY_REFUNDED` or `REBILLED`. `billable_count` is the size of that set, and `gross_invoice_cents` is the sum of the included charges' `publisher_share_cents`, each already rounded to whole cents per §2.6. A charge refunded through a granted opt-out therefore contributes exactly nothing and is not counted at all — the publisher is paid for heads that stayed enrolled and billed.

**Method `ACCESS_DAYS_WEIGHTED`.** The included set is every in-scope charge whose `access_status` is `PROVISIONED`, `REVOKED` or `RESTORED` — that is, every charge that was ever provisioned, whether or not it was later refunded. For each included charge the system establishes an access-from date as the later of the calendar date of the charge's `access_start_at` and the adoption's `access_start_date`. It establishes an access-until date as follows: for a charge whose `access_status` is `REVOKED`, it is the earlier of the day before the calendar date of `access_revoked_at` and the term's `term_end_date`; for any other included charge it is the term's `term_end_date`. The number of access days is the count of days from access-from through access-until inclusive — their difference in days plus one — but never less than zero. That day count is divided by `total_term_days` and rounded half up to 4 decimal places to give the charge's weight, and the charge's `publisher_share_cents` multiplied by that weight, rounded half up to whole cents, is its weighted share. `billable_count` is the number of included charges whose weight is strictly greater than zero, and `gross_invoice_cents` is the sum of the weighted shares. Because a refunded charge's `net_billed_cents` is 0 and therefore its `publisher_share_cents` is 0, this method reconstructs the pre-refund publisher share — for any included charge at all whose computed `publisher_share_cents` comes out 0 while its `refunded_amount_cents` is positive — as that `refunded_amount_cents` multiplied by one minus the agreement's `bookstore_margin_pct`, rounded half up to whole cents, and weights that figure instead. The consequence is the whole reason two methods exist: over identical stored data, whenever any opt-out was granted mid-window, `ACCESS_DAYS_WEIGHTED` yields a strictly larger `gross_invoice_cents` than `ENROLLMENT_SNAPSHOT`, because the publisher is paid for the days access actually existed rather than for the final enrollment picture.

**Rebate, settlement and variance.** These four figures are resolved in exactly this order, and the order matters because the rebate looks circular otherwise. First, `gross_invoice_cents` is the total just computed. Second, `rebate_cents` is `gross_invoice_cents` multiplied by the agreement's `rebate_pct` and rounded half up to whole cents when `gross_invoice_cents` is at or above the agreement's `rebate_threshold_cents`, and 0 when it is below that threshold — the threshold is tested against the *gross* invoice. Third, `settlement_amount_cents` is `gross_invoice_cents` minus `rebate_cents`; the threshold is never re-tested against the settlement amount, even when subtracting the rebate drops the figure back under the threshold. Fourth, the two variances against the publisher's own numbers: `count_variance` is `publisher_reported_count` minus `billable_count`, and `variance_cents` is `publisher_reported_amount_cents` minus `settlement_amount_cents`. Both may be negative.

**Disputing.** When the campus and publisher figures disagree materially, a `ProgramAdmin` disputes the run, moving it `COMPUTED` → `DISPUTED` with a stored `dispute_note`. This requires the run to be `COMPUTED`, to be the current computed run for its agreement and term, the agreement's own `reconciliation_status` to be `COMPUTED` as well — each of those three failing as `ERR_INVALID_STATE` — and its `variance_cents` to have an absolute value strictly greater than five dollars — 500 cents. A dispute filed on a variance whose absolute value is within that tolerance is rejected with `ERR_VARIANCE_WITHIN_TOLERANCE`. Disputing also moves the agreement's `reconciliation_status` `COMPUTED` → `DISPUTED` and increments the agreement's `version`.

**Going stale.** Whenever an opt-out grant, an opt-out rescind, an enrollment drop or a title-change rebill touches a charge priced by a title of the agreement, the agreement's `reconciliation_status` moves to `STALE` — from `COMPUTED` and equally from `DISPUTED` — and the agreement's `version` increments. Going stale has a compliance consequence beyond settlement: while any agreement of the term is `STALE`, disclosure certification is blocked with `ERR_RECONCILIATION_NOT_CURRENT` until a fresh run is computed.

**Settling.** Settlement is a `ProgramAdmin` action with two branches that join at the same state but write different money. Both branches require the term to be `BILLING_LOCKED`, rejecting otherwise with `ERR_TERM_NOT_LOCKED`, and both stamp `settled_at` and `settled_by_user_id` on the run.

The direct branch moves a run `COMPUTED` → `SETTLED`. It requires the run to be `COMPUTED`, the agreement's `reconciliation_status` to be `COMPUTED`, and the absolute value of `variance_cents` to be at most five dollars — 500 cents — with a larger variance rejected as `ERR_VARIANCE_TOLERANCE_EXCEEDED` and required to be disputed first. Its first hop moves the agreement's `reconciliation_status` to `SETTLED` and writes the agreement's `settled_amount_cents` as the run's own `settlement_amount_cents` — the campus computation stands.

The conceded branch moves a run `DISPUTED` → `SETTLED`. It requires the run to be `DISPUTED` and the agreement's `reconciliation_status` to be `DISPUTED`, and it applies no tolerance test at all, because the whole point of a dispute is that the variance is large. Its first hop moves the agreement's `reconciliation_status` to `SETTLED` but writes the agreement's `settled_amount_cents` as the run's `publisher_reported_amount_cents` — the publisher's figure is conceded. This divergence between the two branches is the single most important asymmetry in the settlement flow, and both branches increment the agreement's `version`.

From either branch, the second hop moves the term `BILLING_LOCKED` → `CLOSED` once every agreement pricing at least one charge of that term is `SETTLED`, and the third hop moves every `CERTIFIED` disclosure report of that term to `PUBLISHED`. `SETTLED` is terminal for both the run and the agreement's settlement dimension.

### 3.9. Affordability Reporting and State Disclosure Compliance

A `ComplianceOfficer` owns the state textbook cost disclosure and nothing else — the role cannot flag sections, post charges or settle publishers. A **DisclosureReport** is opened against a term with a payload carrying the `term_id` and a `reporting_state_code` of exactly two uppercase letters; only one report may exist per pairing of term and state code. A new report is `DRAFT` with `amendment_count` at 0, `amendment_note`, `certified_by_user_id`, `certified_at` and `published_at` all null, and every affordability metric computed immediately at creation.

The metrics are recomputed from scratch at three moments: when the report is created, when it is certified, and when it is amended. Their scope is the term's sections that carry `inclusive_access_flag` true, and within those sections the charges whose `billing_status` is `POSTED`, `PARTIALLY_REFUNDED` or `REBILLED`. `ia_section_count` is the number of in-scope sections. `charge_count` is the number of in-scope charges. `enrolled_student_count` is the number of enrollments on in-scope sections whose `status` is `ENROLLED`. `opted_out_student_count` is the number of *distinct* students among all charges on in-scope sections that have at least one opt-out request in `GRANTED` status — this count deliberately reaches beyond the money scope, so a student whose charge was fully refunded is still counted here even though that charge contributes nothing to any money total. `total_list_price_cents` is the sum, over the in-scope charges, of the `locked_list_price_cents` pinned on each charge's adoption at approval — the frozen publisher list price, not the title's possibly-changed current one. `total_net_billed_cents` is the sum of the in-scope charges' `net_billed_cents`. `average_net_cost_cents` is `total_net_billed_cents` divided by `charge_count`, rounded half up to whole cents, or 0 when `charge_count` is zero. `savings_pct` is one minus the quotient of `total_net_billed_cents` over `total_list_price_cents`, rounded half up to 4 decimal places, or 0.0000 when `total_list_price_cents` is zero.

`compliance_status` follows from those figures in a fixed order: it is `NOT_APPLICABLE` when `charge_count` is zero, `COMPLIANT` when `savings_pct` is at or above thirty percent (0.3000), and `NON_COMPLIANT` otherwise. A savings figure of exactly 0.3000 is compliant.

Certification moves the report `DRAFT` → `CERTIFIED`. It requires the report to be `DRAFT`, the current logical date to be on or before the term's `disclosure_deadline_date` — a later attempt is rejected with `ERR_DISCLOSURE_DEADLINE_PASSED` — and every `PublisherAgreement` pricing at least one charge of the term to have a `reconciliation_status` of `COMPUTED`, `DISPUTED` or `SETTLED`. An agreement sitting at `NOT_STARTED` or `STALE` blocks certification with `ERR_RECONCILIATION_NOT_CURRENT`, which is what stops an officer from filing a savings figure that a mid-flight refund has already invalidated. Certification recomputes every metric, then stamps `certified_at` and `certified_by_user_id`.

Amendment is the return path. A `ComplianceOfficer` moves a report `CERTIFIED` → `DRAFT` with a stored `amendment_note`, incrementing `amendment_count` by 1, clearing `certified_at` and `certified_by_user_id`, and recomputing every metric. The loop `DRAFT` → `CERTIFIED` → `DRAFT` may run repeatedly for amended filings.

Publication is not a request anyone makes. The server moves a report `CERTIFIED` → `PUBLISHED` as the third hop of the settlement cascade of §3.8, when and only when the term has reached `CLOSED`, stamping `published_at` and freezing the metrics permanently. `PUBLISHED` is terminal: a published report can never be amended, and an attempt is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — every state transition, every cascade trigger — return `200 OK`, as do all reads. The logical-clock operation returns `200 OK`. Request and response bodies are not restated here; the field-level contract for each operation lives in the §3 narrative that describes the business event it drives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| `POST` | `/_clock/set_current_utc` | Set the logical clock that every date and datetime decision in this API reads; the default before any call is 2026-08-01T00:00:00Z | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `Student`, `ComplianceOfficer` |
| `POST` | `/terms` | Create an academic term with its census, add/drop, late-registration, adoption and disclosure calendar | `ProgramAdmin` |
| `GET` | `/terms/{term_id}` | Read one term | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/terms` | List terms | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/terms/{term_id}/open` | Open the term for section flagging, enrollment and billing | `ProgramAdmin` |
| `POST` | `/terms/{term_id}/lock-billing` | Lock the term's billing so reconciliation can be settled | `ProgramAdmin` |
| `GET` | `/terms/{term_id}/sections` | List the sections of a term | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/terms/{term_id}/disclosure-reports` | List the state disclosure reports of a term | `ProgramAdmin`, `ComplianceOfficer` |
| `POST` | `/students` | Create a student record with a zero bursar balance | `Registrar` |
| `GET` | `/students/{student_id}` | Read one student including the derived bursar balance | `ProgramAdmin`, `Registrar`, `BursarOfficer`, `ComplianceOfficer`, `Student` |
| `GET` | `/students` | List students | `ProgramAdmin`, `Registrar`, `BursarOfficer` |
| `GET` | `/students/{student_id}/enrollments` | List a student's enrollments | `ProgramAdmin`, `Registrar`, `BursarOfficer`, `Student` |
| `GET` | `/students/{student_id}/charges` | List a student's inclusive access charges | `ProgramAdmin`, `Registrar`, `BursarOfficer`, `Student` |
| `GET` | `/students/{student_id}/ledger-entries` | Read the append-only bursar movements of one student | `ProgramAdmin`, `BursarOfficer`, `Student` |
| `POST` | `/agreements` | Create a publisher agreement in DRAFT with its fee, margin, cap, floor and rebate terms | `ProgramAdmin` |
| `GET` | `/agreements/{agreement_id}` | Read one agreement with both state dimensions | `ProgramAdmin`, `Faculty`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/agreements` | List agreements | `ProgramAdmin`, `Faculty`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/agreements/{agreement_id}/activate` | Activate a DRAFT agreement once every active title has at least one pricing tier | `ProgramAdmin` |
| `POST` | `/agreements/{agreement_id}/suspend` | Suspend an ACTIVE agreement, blocking approvals and further charge posting on its titles | `ProgramAdmin` |
| `GET` | `/agreements/{agreement_id}/titles` | List the titles priced by one agreement | `ProgramAdmin`, `Faculty`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/agreements/{agreement_id}/reconciliation-runs` | List the reconciliation runs of one agreement | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/titles` | Register a course material title under an agreement | `ProgramAdmin` |
| `GET` | `/titles/{title_id}` | Read one title | `ProgramAdmin`, `Faculty`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/titles` | List titles, optionally filtered by the agreement that prices them | `ProgramAdmin`, `Faculty`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/titles/{title_id}/withdraw` | Withdraw a title from the inclusive access catalog | `ProgramAdmin` |
| `POST` | `/titles/{title_id}/pricing-tiers` | Add a non-overlapping enrollment band with its negotiated per-student price | `ProgramAdmin` |
| `GET` | `/titles/{title_id}/pricing-tiers` | List the enrollment bands of a title | `ProgramAdmin`, `Faculty`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/pricing-tiers/{tier_id}` | Read one pricing tier | `ProgramAdmin`, `Faculty`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/pricing-tiers` | List pricing tiers, optionally filtered by title | `ProgramAdmin`, `Faculty`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/sections` | Create a course section owned by a Faculty operator | `Registrar`, `ProgramAdmin` |
| `GET` | `/sections/{section_id}` | Read one section with its live counters and participation rate | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/sections` | List sections, optionally filtered by term | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/sections/{section_id}/flag-inclusive-access` | Flag the section for day-one LMS material delivery under its approved adoption | `ProgramAdmin` |
| `GET` | `/sections/{section_id}/adoptions` | List the adoptions of a section | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/sections/{section_id}/enrollments` | List the enrollments of a section | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer` |
| `GET` | `/sections/{section_id}/billing-summary` | Computed read exposing both tier-basis variants of the per-student price side by side plus the section money rollup | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/sections/{section_id}/post-charges` | Batch-post day-one charges for every uncharged ENROLLED student of the section and provision LMS access | `BursarOfficer`, `ProgramAdmin` |
| `POST` | `/adoptions` | Author a faculty adoption in DRAFT, optionally as a title change superseding the section's approved adoption | `Faculty` |
| `GET` | `/adoptions/{adoption_id}` | Read one adoption | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/adoptions` | List adoptions, optionally filtered by section, title or the adoption they supersede | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/adoptions/{adoption_id}/submit` | Submit or resubmit an adoption for program approval | `Faculty` |
| `POST` | `/adoptions/{adoption_id}/request-change` | Return a submitted adoption to the instructor for revision | `ProgramAdmin` |
| `POST` | `/adoptions/{adoption_id}/approve` | Approve an adoption, pin its list price and, for a title change, supersede and rebill the prior adoption | `ProgramAdmin` |
| `POST` | `/adoptions/{adoption_id}/withdraw` | Withdraw an approved adoption before any charge has posted on its section | `ProgramAdmin` |
| `POST` | `/enrollments` | Register a student in a section; the registration date drives proration | `Registrar` |
| `GET` | `/enrollments/{enrollment_id}` | Read one enrollment | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer` |
| `GET` | `/enrollments` | List enrollments, optionally filtered by section or student | `ProgramAdmin`, `Faculty`, `Registrar`, `BursarOfficer` |
| `POST` | `/enrollments/{enrollment_id}/drop` | Drop an enrollment, prorate any posted charge and revoke LMS access | `Registrar` |
| `GET` | `/enrollments/{enrollment_id}/charges` | List the charges of one enrollment | `ProgramAdmin`, `Registrar`, `BursarOfficer`, `Student` |
| `POST` | `/enrollments/{enrollment_id}/post-charge` | Post a single day-one charge for one, usually late-registered, enrollment | `BursarOfficer`, `ProgramAdmin` |
| `GET` | `/charges/{charge_id}` | Read one charge with both of its state dimensions and its money fields | `ProgramAdmin`, `Registrar`, `BursarOfficer`, `ComplianceOfficer`, `Student` |
| `GET` | `/charges` | List charges, optionally filtered by enrollment, adoption or student | `ProgramAdmin`, `Registrar`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/charges/{charge_id}/ledger-entries` | Read the append-only bursar movements of one charge in posting order | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer`, `Student` |
| `GET` | `/charges/{charge_id}/opt-out-requests` | List the opt-out requests filed against one charge | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer`, `Student` |
| `GET` | `/ledger-entries/{entry_id}` | Read one immutable bursar movement | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/ledger-entries` | List bursar movements, optionally filtered by charge or student | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/opt-out-requests` | File an opt-out against a posted charge inside its opt-out window | `Student` |
| `GET` | `/opt-out-requests/{request_id}` | Read one opt-out request | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer`, `Student` |
| `GET` | `/opt-out-requests` | List opt-out requests, optionally filtered by charge | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/opt-out-requests/{request_id}/grant` | Grant an opt-out: refund the bursar charge and revoke LMS access | `BursarOfficer` |
| `POST` | `/opt-out-requests/{request_id}/deny` | Deny an opt-out with a reason note; no money and no access change | `BursarOfficer` |
| `POST` | `/opt-out-requests/{request_id}/rescind` | Student opts back in: re-charge the bursar account and restore LMS access | `Student` |
| `POST` | `/opt-out-requests/{request_id}/resubmit` | Re-file a rescinded opt-out, at most twice over its lifetime | `Student` |
| `POST` | `/reconciliation-runs` | Compute a publisher reconciliation for one agreement-and-term pairing under the chosen method and compare it with the publisher's invoice | `ProgramAdmin` |
| `GET` | `/reconciliation-runs/{run_id}` | Read one reconciliation run with its invoice, rebate and variance figures | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer` |
| `GET` | `/reconciliation-runs` | List reconciliation runs, optionally filtered by agreement, term or the run they supersede | `ProgramAdmin`, `BursarOfficer`, `ComplianceOfficer` |
| `POST` | `/reconciliation-runs/{run_id}/dispute` | Dispute a run whose variance against the publisher invoice exceeds tolerance | `ProgramAdmin` |
| `POST` | `/reconciliation-runs/{run_id}/settle` | Settle a run against the publisher, closing the term and publishing certified disclosures | `ProgramAdmin` |
| `POST` | `/disclosure-reports` | Open a state textbook cost disclosure draft for a term | `ComplianceOfficer` |
| `GET` | `/disclosure-reports/{report_id}` | Read one disclosure report with its affordability metrics and compliance verdict | `ProgramAdmin`, `ComplianceOfficer`, `BursarOfficer` |
| `GET` | `/disclosure-reports` | List disclosure reports, optionally filtered by term | `ProgramAdmin`, `ComplianceOfficer`, `BursarOfficer` |
| `POST` | `/disclosure-reports/{report_id}/certify` | Certify the disclosure for state filing once every publisher agreement of the term has a current reconciliation | `ComplianceOfficer` |
| `POST` | `/disclosure-reports/{report_id}/amend` | Reopen a certified disclosure for amendment | `ComplianceOfficer` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_TERM_NOT_FOUND` | 404 |
| `ERR_STUDENT_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_TITLE_NOT_FOUND` | 404 |
| `ERR_TIER_NOT_FOUND` | 404 |
| `ERR_SECTION_NOT_FOUND` | 404 |
| `ERR_ADOPTION_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_CHARGE_NOT_FOUND` | 404 |
| `ERR_LEDGER_ENTRY_NOT_FOUND` | 404 |
| `ERR_OPT_OUT_REQUEST_NOT_FOUND` | 404 |
| `ERR_RUN_NOT_FOUND` | 404 |
| `ERR_REPORT_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TERM_BILLING_LOCKED` | 409 |
| `ERR_TERM_NOT_OPEN` | 409 |
| `ERR_TERM_NOT_LOCKED` | 409 |
| `ERR_SECTION_NOT_FLAGGED` | 409 |
| `ERR_RECONCILIATION_NOT_CURRENT` | 409 |
| `ERR_DISCLOSURE_DEADLINE_PASSED` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVATABLE` | 409 |
| `ERR_ADOPTION_NOT_APPROVED` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_TITLE_WITHDRAWN` | 409 |
| `ERR_TITLE_ALREADY_BILLED` | 409 |
| `ERR_ADOPTION_DEADLINE_PASSED` | 409 |
| `ERR_OPT_OUT_WINDOW_CLOSED` | 409 |
| `ERR_LATE_REGISTRATION_CLOSED` | 409 |
| `ERR_TIER_BAND_OVERLAP` | 409 |
| `ERR_CONCURRENT_TITLE_LIMIT` | 409 |
| `ERR_DUPLICATE_OPT_OUT_OPEN` | 409 |
| `ERR_OPT_OUT_CYCLE_LIMIT` | 409 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_DUPLICATE_RESOURCE_KEY` | 409 |
| `ERR_CHARGE_ALREADY_EXISTS` | 409 |
| `ERR_VARIANCE_TOLERANCE_EXCEEDED` | 409 |
| `ERR_VARIANCE_WITHIN_TOLERANCE` | 409 |
| `ERR_STALE_SECTION_VERSION` | 412 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
| `ERR_AGREEMENT_WINDOW_MISMATCH` | 422 |
| `ERR_SUPERSEDE_TARGET_INVALID` | 422 |
| `ERR_ENROLLMENT_DATE_OUT_OF_RANGE` | 422 |
| `ERR_ACCESS_WINDOW_INVALID` | 422 |
| `ERR_NO_PRICING_TIER` | 422 |
| `ERR_NO_BILLABLE_CHARGES` | 422 |
