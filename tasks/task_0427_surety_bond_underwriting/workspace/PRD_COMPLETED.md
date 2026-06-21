# Surety Bond Underwriting API — Product Requirements Document

## 1. Introduction

A surety operation lives and dies by the discipline with which it commits capacity. Every bond it writes is a three-party promise — the surety guarantees an obligee that a principal will perform — and that promise consumes finite underwriting room: room within a single risk, room across an entire line of business, and room inside the reinsurance treaties that lay off part of each exposure. The Surety Bond Underwriting API exists to make that capacity accounting authoritative. It governs the full arc of an account, from credit-rating a principal and collecting its general indemnity agreement, through quoting and approving an application, binding and issuing the bond under a power of attorney, endorsing it with riders, ceding portions to reinsurers, handling claims and losses, and finally renewing, cancelling, or expiring the obligation.

The system is deliberately segregated by duty. Front-line underwriters quote, bind, and service bonds, but they cannot grant themselves authority over the large risks that must be referred upward; only the senior tier configures programs and treaties and signs off on referred business. Claims handling is walled off from underwriting entirely. Layered on top of this human workflow is a continuously reconciled exposure ledger: as bonds are bound, riders applied, cessions taken and recaptured, and losses paid, the program's committed and available room and each treaty's ceded balances are kept exact, in integer cents, so that no operation can quietly overcommit the book. This document specifies the entities, state machines, monetary calculations, validation order, endpoints, and error contract that together enforce that discipline.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. A request missing the role header, or carrying a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly three roles: `Underwriter`, `SeniorUnderwriter`, and `ClaimsExaminer`. An `Underwriter` is the front-line authority over principals, indemnity agreements, applications (creating, submitting, referring, declining, and approving only those that fall below the referral threshold and are still in the submitted stage), binding and issuing bonds, the rest of the bond lifecycle, riders, and cessions. A `SeniorUnderwriter` may do everything an `Underwriter` may do, and in addition owns the operations reserved to the senior tier: creating and suspending programs, creating and closing treaties, and approving applications that have been referred. A `ClaimsExaminer` handles claims exclusively — filing, investigating, and settling them — and may read bonds, programs, and claims for context, but may never underwrite, bind, or approve.

For all three roles, `X-User-ID` is an opaque operator identifier and is not tied to any persisted entity. The server treats it purely as the identity of the caller for authentication purposes; it does not compare `X-User-ID` to any entity's `id`, and ownership of a resource is never determined by matching it against a stored foreign key. Authorization is governed entirely by `X-User-Role` together with the operation being attempted.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100 — an out-of-range value is silently clamped into that range (a `limit` below 1 becomes 1, a `limit` above 100 becomes 100) rather than rejected. The `offset` parameter sets how many items are skipped before the page begins and defaults to 0; a negative `offset` is silently clamped to 0. A `limit` or `offset` that is present but not parseable as an integer is rejected with `ERR_INVALID_REQUEST`.

Unless an endpoint states otherwise, every list is returned sorted by the resource's creation timestamp in ascending order — that is, oldest first by `created_at`.

Each list response carries its pagination state in the `meta` object of the envelope through the fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of matching resources across all pages and `has_more` indicates whether further pages remain beyond the current one.

### 2.4. Common Resource Properties and Concurrency Semantics

Every primary resource in this system — `SuretyProgram`, `Principal`, `IndemnityAgreement`, `BondApplication`, `Bond`, `Claim`, `Rider`, `ReinsuranceTreaty`, and `Cession` — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recorded when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation of the resource. The `version` is an integer that begins at its initial value when the resource is created and increases by one on every mutation. All nine of these entities carry the full set; none of them is creation-immutable, so all of them expose `updated_at` and `version`.

Because exposure in this domain is shared across entities, a single request commonly mutates several resources at once. Whenever the server changes a resource — whether by an explicit transition or by a recomputation cascading from another entity's change — that resource's `updated_at` is refreshed and its `version` is incremented. This includes the derived exposure fields: when a bond bind raises a program's committed exposure, the program is itself mutated and its `version` advances.

### 2.5. Optimistic Concurrency Control on Renewal

Renewing a bond is the one operation in this system protected by optimistic concurrency control. Renewal is a create-with-supersede: it spawns a successor bond and retires the predecessor, and it must not be performed against a stale view of the bond. The renew request therefore requires a non-optional `expected_bond_version` field carrying the client's last observed `version` of the target `Bond`. If `expected_bond_version` does not equal the bond's current `version` at the moment the server processes the request, the renewal is rejected with `ERR_STALE_VERSION` and HTTP status 412. This guards against the case where an intervening rider application or cession recapture has already advanced the bond's `version` since the client last read it; the client must re-read the bond and retry with the current version before it can supersede a bond it has not observed in its latest form. No other endpoint accepts a version field, and no other operation performs this check.

### 2.6. Program Exposure Accounting

Each `SuretyProgram` maintains a live picture of how much room it has committed and how much remains. The committed figure, `aggregate_committed_cents`, is the sum of `net_retained_cents` across every bond whose `program_id` is this program and whose status is either `ISSUED` or `ACTIVE`; bonds in `RENEWED`, `CANCELLED`, or `EXPIRED` are excluded from the sum. The available figure, `aggregate_available_cents`, is the program's `aggregate_limit_cents` minus its `aggregate_committed_cents`. A program also publishes its `single_limit_cents`, the largest penal sum any one bond bound under it may carry; its `referral_threshold_cents`, the penal sum at or above which an application must be referred before it can be approved; and its `loss_alert_threshold_cents`, described in §2.7. A program is created with `aggregate_committed_cents` initialized to 0 and `status` set to `OPEN`; the only other status is `SUSPENDED`.

A bond's own retained exposure is `net_retained_cents`, equal to its `penal_sum_cents` minus its `ceded_penal_sum_cents`, where `ceded_penal_sum_cents` is the sum of the ceded amounts over the bond's `ACTIVE` cessions. This retained figure — never the gross penal sum — is what the program charges against its aggregate. The committed total is maintained incrementally as bonds bind, renew, cancel, and expire, as riders apply, and as cessions are created and recaptured, and at all times it reconciles to the defining sum above. All exposure figures are integer cents.

### 2.7. Loss Accumulation and the Loss-Alert Brake

A bond tracks the loss running against it in `incurred_loss_cents`. This figure aggregates, over every claim filed against the bond, two distinct views of the same claim set: for each claim still in `FILED` or `INVESTIGATING`, its case reserve (`reserve_cents`) contributes; for each claim that has reached `PAID`, the realized net loss contributes in place of any reserve — that net loss is the paid loss minus salvage, taken as `paid_loss_cents` minus `salvage_cents` but floored at zero so that salvage can never drive a single claim's contribution below zero; and each `DENIED` claim contributes nothing. The result is integer cents.

Independently of the aggregate-capacity brake, each program carries a `loss_alert_threshold_cents`. Whenever a claim settlement pays a loss, the program's cumulative incurred loss — the sum of `incurred_loss_cents` over all the program's bonds — is recomputed, and if that cumulative figure is at or above the program's `loss_alert_threshold_cents`, the program is automatically driven to `SUSPENDED`. This loss brake is separate from and additional to the aggregate-limit constraint; a program may suspend on losses while still having aggregate room, or run out of aggregate room while well under its loss alert.

### 2.8. Treaty Capacity and Cession Accounting

A `ReinsuranceTreaty` accepts quota-share cessions up to a fixed ceiling. Its `cession_pct_bps` is the quota-share percentage expressed in basis points — for example, a value of 3000 means thirty percent — applied to each ceded bond's penal sum. Its `treaty_capacity_cents` is the maximum total ceded penal sum it will hold across its `ACTIVE` cessions. The treaty publishes `ceded_committed_cents`, the sum of `ceded_penal_sum_cents` over its `ACTIVE` cessions, and `ceded_available_cents`, equal to `treaty_capacity_cents` minus `ceded_committed_cents`. A treaty is created with `ceded_committed_cents` at 0 and `status` of `OPEN`; the only other status is `CLOSED`.

### 2.9. Monetary Precision and Rounding

All monetary quantities in this system are integer cents. Wherever a calculation produces a fractional cent before it is stored — premium quotes, earned premium, additional rider premium, and ceded amounts all involve a division — the result is rounded half up to the nearest whole cent. "Round half up" means a value whose fractional part is exactly one-half rounds away from zero to the next whole cent. Threshold and limit comparisons throughout the system are integer comparisons, and unless a rule states a strict inequality, boundaries are inclusive.

### 2.10. The Logical Clock

Several premium calculations depend on how much of a bond's term has elapsed, which the system measures against a server-controlled logical clock rather than wall-clock time. Before any clock call is made, the logical clock reads `2026-01-01T00:00:00Z`; the server never falls back to wall-clock time. The senior tier may advance the clock by supplying a target instant in the `to_iso8601` field, expressed as an ISO 8601 UTC instant; a missing or non-string `to_iso8601`, or one that does not parse as an ISO 8601 instant, is rejected with `ERR_INVALID_REQUEST`. A successful clock set returns HTTP 200 with an empty object (`{}`) in the `data` field rather than any resource. The clock value governs the elapsed-month measurement used by earned-premium and rider-premium math described in §3.

### 2.11. Reference Resolution Order

When a request references resources — by path identifier or by foreign-key fields in the body — the system validates their existence left to right, in the order they appear, and rejects the request with `ERR_NOT_FOUND` at the first reference that does not resolve to an existing resource. Only once every referenced resource is confirmed to exist does the system proceed to body-shape validation and then to the operation's business rules.

### 2.12. Request Validation and Its Ordering

Across every endpoint, validation proceeds in a fixed priority order so that the same request always fails for the same, most fundamental reason. Authentication comes first: a missing or unrecognized role yields `ERR_UNAUTHENTICATED`. Authorization is second: a recognized role that is not permitted for the operation yields `ERR_FORBIDDEN`. Existence is third: any referenced resource that does not exist yields `ERR_NOT_FOUND`, evaluated left to right as described in §2.11. Request well-formedness is fourth and applies to every write endpoint: required body fields must be present and correctly typed, enum fields must carry a recognized value, and integer fields must fall within their declared ranges — for instance, a principal's credit score must lie within 300 to 850 inclusive — with any violation yielding `ERR_INVALID_REQUEST`. State legality is fifth and applies to every transition endpoint: the target resource must currently be in a state from which the requested transition is defined, or the request is rejected with `ERR_INVALID_STATE`. Sixth, on the renew operation only, the optimistic-concurrency check described in §2.5 applies, yielding `ERR_STALE_VERSION`. Only after these six gates do the operation-specific business rules — indemnity, open-claim, referral, loss, single-limit, aggregate-limit, treaty-capacity, program-suspension, and treaty-closed checks — come into play; those are described alongside the workflows they guard in §3.

## 3. Business Logic & Workflows

### 3.1. Establishing Capacity: Programs and Treaties

Before any business can be written, the senior tier stands up the capacity structures. A `SeniorUnderwriter` creates a `SuretyProgram` by supplying its `name`, `single_limit_cents`, `aggregate_limit_cents`, `referral_threshold_cents`, and `loss_alert_threshold_cents`. The program opens in `OPEN` status with `aggregate_committed_cents` at zero, and from that point its `aggregate_committed_cents` and `aggregate_available_cents` move automatically as bonds come and go, per §2.6.

The senior tier may also take a program out of service. Suspending a program moves it from `OPEN` to `SUSPENDED`; the operation is valid only while the program is `OPEN`, and an attempt to suspend a program that is not `OPEN` is rejected with `ERR_INVALID_STATE`. Once `SUSPENDED`, the program refuses new submit, approve, and bind activity, each such attempt returning `ERR_PROGRAM_SUSPENDED`. A program can also reach `SUSPENDED` without anyone asking, as the terminal hop of a loss settlement, described in §3.7.

In parallel, the senior tier configures reinsurance. Creating a `ReinsuranceTreaty` takes its `name`, its `cession_pct_bps`, and its `treaty_capacity_cents`; it opens `OPEN` with `ceded_committed_cents` at zero. Closing a treaty moves it from `OPEN` to `CLOSED` and is permitted only while it is `OPEN`, with an attempt against a treaty that is not `OPEN` rejected as `ERR_INVALID_STATE`. A `CLOSED` treaty refuses new cessions with `ERR_TREATY_CLOSED`, but cessions already `ACTIVE` against it are left untouched.

### 3.2. Principals, Credit Tiering, and Indemnity

An account begins with the principal. An underwriter (front-line or senior) creates a `Principal` by supplying its `legal_name`, its `credit_score`, and its `working_capital_cents`, the last of which may be negative. The credit score must be an integer from 300 to 850 inclusive; a value outside that band is an `ERR_INVALID_REQUEST`. On creation — and again whenever the principal is updated — the system derives the principal's `credit_tier`. A principal is rated `PREFERRED` when its credit score is at least 720 and its working capital is at least zero; failing that, it is rated `STANDARD` when its credit score is at least 620 and its working capital is at least zero; and in every remaining case — any principal whose working capital is negative, or whose score is below 620 — it is rated `SUBSTANDARD`. The principal also carries an `indemnity_on_file` flag, which starts false and becomes true exactly when at least one `EXECUTED` indemnity agreement references the principal.

Indemnity is collected through a general indemnity agreement, or GIA. An underwriter creates an `IndemnityAgreement` against a principal by supplying that principal's identifier in the body, the `indemnitor_count` (how many personal or corporate indemnitors are signing), and the `required_signature_count` (how many signatures must be collected for the agreement to execute). The agreement opens in `PENDING` status with `collected_signature_count` at zero. Signatures are gathered one at a time: each signing call against a `PENDING` agreement increments `collected_signature_count` by one. As long as collecting one more signature would still leave the running total short of `required_signature_count` — that is, while the count after this signature is strictly less than the required count — the agreement remains in `PENDING` and merely records the new tally. The signature that brings `collected_signature_count` up to exactly `required_signature_count` is the one that executes the agreement: it both increments the count to the required total and transitions the agreement to `EXECUTED`, and as a cross-entity effect it causes the referenced principal's `indemnity_on_file` to be recomputed to true. Signing is only valid while the agreement is `PENDING`; signing one that is not `PENDING` is rejected with `ERR_INVALID_STATE`. An underwriter may instead void a `PENDING` agreement, moving it to `VOIDED`; voiding is likewise valid only from `PENDING`, with `ERR_INVALID_STATE` otherwise. Both `EXECUTED` and `VOIDED` are terminal.

### 3.3. Application, Quote, and the Underwriting Fork

An underwriter opens a `BondApplication` in `DRAFT` by supplying the applicant's principal identifier, the `program_id` the bond would bind to, the `bond_type` (one of `BID`, `PERFORMANCE`, `PAYMENT`, `LICENSE_PERMIT`, or `FIDELITY`), the `requested_penal_sum_cents`, and the `term_months` over which the bond will run. The application carries a `decline_reason` field that is left unset at creation and is only populated if the application is later declined; when supplied it must be one of `OBLIGEE_INELIGIBLE`, `CREDIT`, `CAPACITY`, or `OTHER`.

Submitting a `DRAFT` application moves it to `SUBMITTED` and is the moment the premium is quoted; until that submit the application's `quoted_premium_rate_bps` and `quoted_premium_cents` are both null. Submission is gated by three preconditions evaluated together with the state check: the application must be `DRAFT` (otherwise `ERR_INVALID_STATE`); the applicant principal must already have indemnity on file, meaning an `EXECUTED` GIA exists for it (otherwise `ERR_INDEMNITY_REQUIRED`); and the target program must be `OPEN` (otherwise `ERR_PROGRAM_SUSPENDED`). On a successful submit, the system computes the quote in two fields. First it selects the rate, `quoted_premium_rate_bps`, in basis points, from the intersection of the principal's `credit_tier` and the application's `bond_type` using the published rate schedule: a `PREFERRED` principal is rated 100 for `BID`, 150 for `PERFORMANCE`, 150 for `PAYMENT`, 80 for `LICENSE_PERMIT`, and 120 for `FIDELITY`; a `STANDARD` principal is rated 150, 225, 225, 120, and 180 for those same five bond types in order; and a `SUBSTANDARD` principal is rated 250, 375, 375, 200, and 300 respectively. To that base rate the system adds a flat large-risk surcharge of 50 basis points whenever the request is a large risk — defined as a requested penal sum that, when doubled, is at least the program's `single_limit_cents` (equivalently, a requested penal sum that is at least half the single limit); otherwise the surcharge is zero. The base rate plus any surcharge is then clamped so that `quoted_premium_rate_bps` never exceeds 400 basis points: the stored rate is the smaller of 400 and the surcharged rate. Second, the system computes `quoted_premium_cents` as the requested penal sum multiplied by `quoted_premium_rate_bps`, divided by 10000, with that product rounded half up to whole cents.

From `SUBMITTED`, the application forks. A front-line underwriter may approve it directly, but only when the requested penal sum is strictly below the program's `referral_threshold_cents`; a request at or above that threshold cannot be approved from the submitted stage and is rejected with `ERR_REFERRAL_REQUIRED`, forcing the referral path. A direct approval additionally requires that the requested penal sum not exceed the program's `single_limit_cents`, or it is rejected with `ERR_SINGLE_LIMIT_EXCEEDED`; when both hold, the application moves to `APPROVED`. Alternatively, the underwriter may refer the submitted application, moving it to `REFERRED` and handing authority to the senior tier; referral is valid only from `SUBMITTED`. Approval of a `REFERRED` application is reserved to a `SeniorUnderwriter` — a front-line underwriter cannot approve a referred file, by segregation of duties, and an `Underwriter` who attempts to approve a `REFERRED` application is rejected with `ERR_FORBIDDEN` (the application is left unchanged in `REFERRED`) — and that senior approval is valid only when the application is `REFERRED` and the requested penal sum does not exceed `single_limit_cents` (else `ERR_SINGLE_LIMIT_EXCEEDED`), moving it to `APPROVED`. Either underwriter may decline instead: a decline is valid when the application is in either `SUBMITTED` or `REFERRED` status, records the supplied `decline_reason`, and moves the application to `DECLINED`; a senior may decline a referred file just as a front-line underwriter may decline a submitted one. `DECLINED` and `BOUND` are the application's terminal states.

### 3.4. Binding and Issuing the Bond

Binding turns an approved application into a live obligation. An underwriter binds by supplying the `application_id` of an `APPROVED` application. Binding requires that application to be `APPROVED` (otherwise `ERR_INVALID_STATE`), that the program still be `OPEN` (otherwise `ERR_PROGRAM_SUSPENDED`), and that the program have room — the requested penal sum must not exceed the program's `aggregate_available_cents`, or the bind is rejected with `ERR_AGGREGATE_LIMIT_EXCEEDED`. On success the application moves to `BOUND` and a new `Bond` is created in `ISSUED` status. The bond copies forward, as system-set fields, the `application_id` it was bound from, the `principal_id` and `program_id` from the application, the `bond_type`, the `penal_sum_cents` from the application's requested penal sum, the `term_months`, the `premium_rate_bps` from the application's quoted rate, and the `written_premium_cents` from the application's quoted premium. A freshly bound bond has `earned_premium_cents` of zero, `ceded_penal_sum_cents` of zero, and therefore `net_retained_cents` equal to its full penal sum, with `incurred_loss_cents` of zero and `power_of_attorney_number` not yet assigned. As a cross-entity effect, the program's `aggregate_committed_cents` rises by the new bond's `net_retained_cents`, which at issuance equals the full penal sum since nothing is yet ceded.

A bond does not become enforceable until it is issued under a power of attorney. Issuing a bond that is `ISSUED` mints a server-generated `power_of_attorney_number` — an opaque non-empty string (the implementation emits the form `POA-` followed by twelve uppercase hexadecimal characters) — stamps it onto the bond, and moves the bond to `ACTIVE`; issuing is valid only from `ISSUED`, with `ERR_INVALID_STATE` otherwise. The bond's `superseded_by_bond_id` field remains unset unless and until a renewal replaces it, as described in §3.5.

### 3.5. Servicing the Bond: Riders, Cessions, Renewal, Cancellation, and Expiry

Once a bond is `ACTIVE`, it can be endorsed, reinsured, renewed, or retired.

**Riders.** An underwriter drafts a `Rider` against a bond by supplying that bond's identifier in the `bond_id` field and a `rider_type` of `INCREASE`, `DECREASE`, or `NAME_CHANGE`, optionally with a `penal_sum_delta_cents` — a signed change to the penal sum that is positive for an increase, negative for a decrease, and zero for a name change, defaulting to zero when omitted. The rider opens in `DRAFT`. Applying a draft rider is gated by several conditions: the rider must be `DRAFT` and its bond must be `ACTIVE` (each otherwise an `ERR_INVALID_STATE`); the bond must have no claim in `FILED` or `INVESTIGATING` (otherwise `ERR_OPEN_CLAIM_EXISTS`); and for an `INCREASE` specifically, the bond's resulting penal sum — its current `penal_sum_cents` plus the `penal_sum_delta_cents` — must not exceed the program's `single_limit_cents` (otherwise `ERR_SINGLE_LIMIT_EXCEEDED`), and the increase amount itself must not exceed the program's `aggregate_available_cents` (otherwise `ERR_AGGREGATE_LIMIT_EXCEEDED`). On a successful apply, the system computes the rider's `additional_premium_cents`, adjusts the bond's `penal_sum_cents` by the delta and recomputes its `net_retained_cents`, adjusts the program's `aggregate_committed_cents` by the resulting change in the bond's `net_retained_cents`, and moves the rider to `APPLIED`. For an `INCREASE`, `additional_premium_cents` is a pro-rated additional charge over the remaining term, computed with a pinned rounding order: first take the increase amount multiplied by the bond's `premium_rate_bps`, divided by 10000 and then divided by 12, and round that per-month figure half up to whole cents; then multiply that rounded per-month figure by the number of remaining months. The remaining months are the bond's `term_months` minus the elapsed months, where elapsed months is the number of whole months from the bond's creation to the current logical clock instant, clamped to lie between zero and the bond's `term_months`. The rounding happens on the per-month figure first and the multiplication second — round-then-multiply, never sum-then-round. For a `DECREASE` or a `NAME_CHANGE`, `additional_premium_cents` is zero. An underwriter may instead reject a draft rider, moving it from `DRAFT` to `REJECTED`; rejection is valid only from `DRAFT`. Both `APPLIED` and `REJECTED` are terminal.

**Cessions.** An underwriter cedes part of an active bond's penal sum to a treaty by supplying that bond's identifier in the `bond_id` field and the treaty's identifier in the `treaty_id` field. The system computes the cession's `ceded_penal_sum_cents` at creation as the bond's `penal_sum_cents` multiplied by the treaty's `cession_pct_bps`, divided by 10000, rounded half up to whole cents. A cession is rejected if the treaty is `CLOSED` (`ERR_TREATY_CLOSED`) or if the computed ceded amount would exceed the treaty's `ceded_available_cents` (`ERR_TREATY_CAPACITY_EXCEEDED`). On creation the cession opens `ACTIVE`; the treaty's `ceded_committed_cents` rises by the ceded amount, the bond's `ceded_penal_sum_cents` rises and its `net_retained_cents` correspondingly falls, and the program's `aggregate_committed_cents` falls by the reduction in the bond's `net_retained_cents`. Recapture is the compensating action: an underwriter recaptures an `ACTIVE` cession, which is valid only while the cession is `ACTIVE` and its bond is `ACTIVE` (each otherwise `ERR_INVALID_STATE`). Recapture decrements the treaty's `ceded_committed_cents` by the cession's ceded amount, recomputes the bond's `ceded_penal_sum_cents` so its `net_retained_cents` rises, raises the program's `aggregate_committed_cents` by that rise in retained exposure, and moves the cession to `RECAPTURED`, which is terminal. Recapture conserves total penal sum: it simply returns retained exposure to the program and frees the treaty capacity the cession had been holding.

**Renewal.** Renewing an `ACTIVE` bond is a create-with-supersede protected by the optimistic-concurrency rule of §2.5: the request carries `expected_bond_version`, and a mismatch with the bond's current `version` yields `ERR_STALE_VERSION` (HTTP 412). Beyond the version and state checks, renewal requires that the program have room for the bond afresh — its `aggregate_available_cents` must be at least the bond's `penal_sum_cents`, or the renewal is rejected with `ERR_AGGREGATE_LIMIT_EXCEEDED`. On success the system creates a successor `Bond` in `ISSUED` status copying the predecessor's penal sum, rate, and term; sets the predecessor's `superseded_by_bond_id` to the successor's identifier; moves the predecessor to `RENEWED`; and shifts program exposure from predecessor to successor by releasing the predecessor's `net_retained_cents` from `aggregate_committed_cents` and committing the successor's `penal_sum_cents`. Renewal advances the predecessor bond's `version` by one. The renew response (HTTP 200) returns the predecessor bond in its post-transition form — now in `RENEWED` status with `superseded_by_bond_id` set to the successor's identifier — not the newly created successor; the successor is discoverable by listing bonds filtered on that `superseded_by_bond_id`.

**Cancellation.** An underwriter cancels an `ACTIVE` bond by supplying a `cancel_mode`. Cancellation is valid only while the bond is `ACTIVE` (otherwise `ERR_INVALID_STATE`) and only when the bond has no claim in `FILED` or `INVESTIGATING` (otherwise `ERR_OPEN_CLAIM_EXISTS`). On cancellation the system computes the bond's `earned_premium_cents` according to the `cancel_mode`, which is either `PRO_RATA` or `SHORT_RATE`. In both variants, elapsed months is the whole months from the bond's creation to the current logical clock instant, clamped between zero and the bond's `term_months`, and remaining months is `term_months` minus elapsed months. Under `PRO_RATA` — a voluntary cancel with no penalty — earned premium is the bond's `written_premium_cents` multiplied by elapsed months and divided by `term_months`, rounded half up once to whole cents; the unearned portion is fully returned. Under `SHORT_RATE` — an early cancel at the principal's request, carrying a penalty — earned premium is that same pro-rata earned amount plus an additional penalty equal to ten percent of the unearned portion, where the unearned portion is `written_premium_cents` multiplied by remaining months and divided by `term_months`; the two parts are summed and the single final sum is rounded half up once to whole cents (sum-then-round, not round-per-part), so that less premium is returned than under pro-rata. After computing earned premium, cancellation decrements the program's `aggregate_committed_cents` by this bond's `net_retained_cents` measured before any recapture, then drives every `ACTIVE` cession on the bond to `RECAPTURED`, decrementing each affected treaty's `ceded_committed_cents` by that cession's ceded amount; finally the bond moves to `CANCELLED`.

**Expiry.** An underwriter expires an `ACTIVE` bond at the natural end of its term. Expiry is valid only while the bond is `ACTIVE` (otherwise `ERR_INVALID_STATE`) and only when no claim on the bond is in `FILED` or `INVESTIGATING` (otherwise `ERR_OPEN_CLAIM_EXISTS`). On expiry the bond's `earned_premium_cents` is set equal to its full `written_premium_cents`, since a bond run to term is fully earned; the program's `aggregate_committed_cents` is decremented by the bond's `net_retained_cents` measured before recapture; every `ACTIVE` cession on the bond is driven to `RECAPTURED` with the corresponding treaty `ceded_committed_cents` decrements; and the bond moves to `EXPIRED`. `RENEWED`, `CANCELLED`, and `EXPIRED` are all terminal for a bond.

### 3.6. Filing and Investigating Claims

Claims are the province of the `ClaimsExaminer`, who may neither underwrite nor approve. An examiner files a `Claim` against a bond by supplying the bond's identifier, the `claimant_name` of the obligee bringing the claim, the `demand_cents` being demanded, and the initial case `reserve_cents`. The claim opens in `FILED`, and filing it recomputes the bond's `incurred_loss_cents` to fold in the new reserve. A claim may carry, when it is eventually settled, a `paid_loss_cents` figure and a `salvage_cents` recovery, the latter defaulting to zero; at filing `paid_loss_cents` is null while `salvage_cents` is initialized to 0 (not null).

Moving a claim from `FILED` to `INVESTIGATING` is valid only when the claim is `FILED` and the bond it is filed against is `ACTIVE` (each otherwise `ERR_INVALID_STATE`). The investigate call carries an updated `reserve_cents`, which replaces the claim's reserve, and the bond's `incurred_loss_cents` is recomputed to reflect the revised estimate.

### 3.7. Settling Claims and the Loss Cascade

A claim is settled out of `INVESTIGATING` to one of two terminal outcomes, chosen by the settle call's `outcome` field. Settling is valid only while the claim is `INVESTIGATING` (otherwise `ERR_INVALID_STATE`).

When the `outcome` is to pay, the settle call must carry `paid_loss_cents`, and that amount must not exceed the bond's `penal_sum_cents`, or the settlement is rejected with `ERR_LOSS_EXCEEDS_PENAL_SUM`. The call may also carry a `salvage_cents` recovery applied from indemnitors or collateral. On a paying settlement the claim records its `paid_loss_cents` and `salvage_cents` and moves to `PAID`, and the bond's `incurred_loss_cents` is recomputed: this claim's reserve drops out of the estimate and its realized net loss — the paid loss minus salvage, floored at zero — takes its place. After the bond's loss is recomputed, the loss cascade reaches the program: the program's cumulative incurred loss, the sum of `incurred_loss_cents` over all the program's bonds, is recomputed, and if that total is at or above the program's `loss_alert_threshold_cents`, the program is driven to `SUSPENDED` as the terminal hop of the settlement — the loss-alert brake of §2.7.

When the `outcome` is to deny, the claim simply moves to `DENIED` and the bond's `incurred_loss_cents` is recomputed by removing this claim's reserve and adding nothing in its place. Both `PAID` and `DENIED` are terminal; a denied claim, like a paid one, no longer holds a reserve against the bond.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state transition and every signing, applying, settling, or recapturing action — return a `200 OK` status code, as do read operations. The full request and response shape for each operation, including every input field and every cascading side effect, is specified in the §3 narratives and the §2 global principles; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/surety/programs` | Create a surety program with single/aggregate/referral limits and loss-alert threshold | SeniorUnderwriter |
| GET | `/surety/programs/{id}` | Get a program with live aggregate exposure | Underwriter, SeniorUnderwriter, ClaimsExaminer |
| GET | `/surety/programs` | List programs (paginated) | Underwriter, SeniorUnderwriter, ClaimsExaminer |
| POST | `/surety/programs/{id}/suspend` | Suspend a program | SeniorUnderwriter |
| POST | `/surety/principals` | Create a principal; credit tier derived | Underwriter, SeniorUnderwriter |
| GET | `/surety/principals/{id}` | Get a principal | Underwriter, SeniorUnderwriter, ClaimsExaminer |
| POST | `/surety/indemnity-agreements` | Create a general indemnity agreement for a principal | Underwriter, SeniorUnderwriter |
| GET | `/surety/indemnity-agreements/{id}` | Get a GIA | Underwriter, SeniorUnderwriter |
| GET | `/surety/indemnity-agreements` | List GIAs, filterable by principal | Underwriter, SeniorUnderwriter |
| POST | `/surety/indemnity-agreements/{id}/sign` | Add one signature; executes the GIA when the last required signature is collected | Underwriter, SeniorUnderwriter |
| POST | `/surety/indemnity-agreements/{id}/void` | Void a pending GIA | Underwriter, SeniorUnderwriter |
| POST | `/surety/applications` | Create a bond application in DRAFT | Underwriter, SeniorUnderwriter |
| GET | `/surety/applications/{id}` | Get an application including quoted premium | Underwriter, SeniorUnderwriter |
| GET | `/surety/applications` | List applications, filterable by principal and program | Underwriter, SeniorUnderwriter |
| POST | `/surety/applications/{id}/submit` | Submit a DRAFT application; computes premium quote | Underwriter, SeniorUnderwriter |
| POST | `/surety/applications/{id}/approve` | Approve a SUBMITTED (front-line) or REFERRED (senior) application | Underwriter, SeniorUnderwriter |
| POST | `/surety/applications/{id}/refer` | Refer a SUBMITTED application to senior authority | Underwriter, SeniorUnderwriter |
| POST | `/surety/applications/{id}/decline` | Decline a SUBMITTED or REFERRED application | Underwriter, SeniorUnderwriter |
| POST | `/surety/bonds` | Bind an APPROVED application into a Bond | Underwriter, SeniorUnderwriter |
| GET | `/surety/bonds/{id}` | Get a bond including exposure and loss fields | Underwriter, SeniorUnderwriter, ClaimsExaminer |
| GET | `/surety/bonds` | List bonds, filterable by application, principal, program, and superseding bond | Underwriter, SeniorUnderwriter, ClaimsExaminer |
| POST | `/surety/bonds/{id}/issue` | Issue a bond: mint power-of-attorney and activate | Underwriter, SeniorUnderwriter |
| POST | `/surety/bonds/{id}/cancel` | Cancel an ACTIVE bond; compute earned premium; recapture cessions | Underwriter, SeniorUnderwriter |
| POST | `/surety/bonds/{id}/renew` | Renew an ACTIVE bond (create-with-supersede); OCC on bond version | Underwriter, SeniorUnderwriter |
| POST | `/surety/bonds/{id}/expire` | Expire an ACTIVE bond at end of term | Underwriter, SeniorUnderwriter |
| POST | `/surety/claims` | File a claim against a bond | ClaimsExaminer |
| GET | `/surety/claims/{id}` | Get a claim | Underwriter, SeniorUnderwriter, ClaimsExaminer |
| GET | `/surety/claims` | List claims, filterable by bond | Underwriter, SeniorUnderwriter, ClaimsExaminer |
| POST | `/surety/claims/{id}/investigate` | Move a FILED claim to INVESTIGATING; update reserve | ClaimsExaminer |
| POST | `/surety/claims/{id}/settle` | Settle a claim PAY or DENY | ClaimsExaminer |
| POST | `/surety/riders` | Create a rider (endorsement) on a bond in DRAFT | Underwriter, SeniorUnderwriter |
| GET | `/surety/riders/{id}` | Get a rider | Underwriter, SeniorUnderwriter |
| GET | `/surety/riders` | List riders, filterable by bond | Underwriter, SeniorUnderwriter |
| POST | `/surety/riders/{id}/apply` | Apply a DRAFT rider; adjusts bond penal sum and program exposure | Underwriter, SeniorUnderwriter |
| POST | `/surety/riders/{id}/reject` | Reject a DRAFT rider | Underwriter, SeniorUnderwriter |
| POST | `/surety/treaties` | Create a reinsurance treaty (quota share) | SeniorUnderwriter |
| GET | `/surety/treaties/{id}` | Get a treaty including live ceded balances | Underwriter, SeniorUnderwriter |
| GET | `/surety/treaties` | List treaties (paginated) | Underwriter, SeniorUnderwriter |
| POST | `/surety/treaties/{id}/close` | Close a treaty to new cessions | SeniorUnderwriter |
| POST | `/surety/cessions` | Cede part of a bond's penal sum to a treaty | Underwriter, SeniorUnderwriter |
| GET | `/surety/cessions/{id}` | Get a cession | Underwriter, SeniorUnderwriter |
| GET | `/surety/cessions` | List cessions, filterable by bond and treaty | Underwriter, SeniorUnderwriter |
| POST | `/surety/cessions/{id}/recapture` | Recapture an ACTIVE cession (compensating action) | Underwriter, SeniorUnderwriter |
| POST | `/surety/_clock/set_current_utc` | Set the server logical clock to an ISO-8601 UTC instant | SeniorUnderwriter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INDEMNITY_REQUIRED` | 409 |
| `ERR_REFERRAL_REQUIRED` | 409 |
| `ERR_SINGLE_LIMIT_EXCEEDED` | 409 |
| `ERR_AGGREGATE_LIMIT_EXCEEDED` | 409 |
| `ERR_TREATY_CAPACITY_EXCEEDED` | 409 |
| `ERR_TREATY_CLOSED` | 409 |
| `ERR_PROGRAM_SUSPENDED` | 409 |
| `ERR_OPEN_CLAIM_EXISTS` | 409 |
| `ERR_LOSS_EXCEEDS_PENAL_SUM` | 409 |
