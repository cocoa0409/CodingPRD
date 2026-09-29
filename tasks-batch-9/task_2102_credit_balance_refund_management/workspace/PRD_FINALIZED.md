# Credit Balance & Refund Management API — Product Requirements Document

## 1. Introduction

Every hospital patient accounting department eventually accumulates money it does not own. A patient pays an estimated share at registration and the payer later remits the full contractual allowance; a secondary payer pays a claim the primary had already settled; a posting clerk applies a remittance to the wrong account number; a contractual adjustment is booked short and the write-down never catches up. The account swings into credit, and from that moment the hospital is holding somebody else's funds under a statutory clock. This document specifies the backend service that finds those credits, explains how they arose, decides who they belong to, gets them approved and paid out by check, and — when the check is never cashed — hands the money to the state.

The regulatory pressure on this workflow is unusual in two respects. First, an overpayment traceable to a federal health care program must be reported and repaid within sixty days of the day the hospital identified it, and lateness is assessed against the reportable amount on a tiered schedule — so the service has to know, to the whole day, when each credit was identified and how far past the deadline it now sits. Second, a refund check that is cut but never presented does not simply expire: it becomes unclaimed property owned by a state escheat authority, and the holder must run a statutory dormancy clock, send an owner-contact letter inside a fixed lead window, and then remit. Both obligations are computed, not entered, and both can be *un*-computed when a check is voided or an offset is reversed. Nothing in this system is fire-and-forget.

Cutting across all of it is a hard segregation-of-duties model. The analyst who identifies a credit and prepares the refund may not approve it. An approver may not supply both signatures on a request that needs two. The treasury operator who assembles and issues the check run holds no approval authority at all. A payer's own representative may record a recoupment notice and dispute it, but may only ever touch notices belonging to its own payer organisation. Meanwhile the ledger underneath must stay honest: every disbursement, offset, escheat remittance and reversal is a posted transaction, balances are always derived from those postings rather than stored independently, and every compensating action posts an exact negation of what it undoes. The remainder of this document specifies the envelope and cross-cutting conventions (§2), the business workflows and their computations (§3), the HTTP surface (§4), and the complete error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. Operating Roles and Access Control

Every request to every endpoint — reads included — must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the capacity in which the caller is acting. If either header is missing, or if `X-User-Role` is not one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the named role is not among the roles authorised for the endpoint being called (see the table in §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles are `CreditAnalyst`, `RefundApprover`, `DisbursementOfficer`, `ComplianceOfficer`, `PayerLiaison` and `SystemAdmin`.

- A `CreditAnalyst` is a patient accounting analyst. Analysts run the identification sweep, take credits into review, determine the patient-versus-payer attribution, file root-cause findings, reverse mis-posted ledger rows, prepare refund requests, submit and cancel them, apply payer take-backs against credit balances and reverse individual offset lines. An analyst holds no approval and no disbursement authority.
- A `RefundApprover` is a signing authority. Its only write capability is deciding on a submitted refund request. It may never decide on a request it prepared itself, and it may never contribute two of the same request's approvals.
- A `DisbursementOfficer` is a treasury operator. It opens check runs, adds approved requests to them, locks and unlocks and issues them, and clears, voids or reissues individual checks. It holds no approval authority.
- A `ComplianceOfficer` owns the regulatory perimeter: the Medicare sixty-day self-report, de-minimis write-offs, the unclaimed-property lifecycle from record creation through due diligence to remittance, and the generation and finalisation of audit reports. It may also run the nightly operations checkpoint.
- A `PayerLiaison` is a payer-side representative. It records take-back notices, disputes them and withdraws those disputes.
- A `SystemAdmin` seeds payers and accounts, moves an account's `status`, drives the logical clock and runs the nightly operations checkpoint. It deliberately holds no analyst, approval, disbursement or compliance authority.

Role identity matters because two different things can live in `X-User-ID`. When `X-User-Role` is `PayerLiaison`, `X-User-ID` is the `id` of the acting `Payer` row; ownership checks on any resource that references a `Payer` compare the resource's payer foreign key to `X-User-ID`. Concretely, a `PayerLiaison` recording a take-back notice must supply a `payer_id` equal to its own `X-User-ID`, and a `PayerLiaison` disputing or withdrawing a dispute on an existing notice must be acting for the payer named on that notice; when it is not, the request is rejected with `ERR_PAYER_SCOPE_VIOLATION` (HTTP 403). For the other five roles — `CreditAnalyst`, `RefundApprover`, `DisbursementOfficer`, `ComplianceOfficer` and `SystemAdmin` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow requires provenance (the preparer of a refund request in `prepared_by_user_id`, the deciding approver in `approver_user_id` and `last_decision_user_id`, the filing analyst in `analyst_user_id`, the report author in `generated_by_user_id`) and compares operator identifiers to each other for segregation-of-duties purposes, but it never compares them to any entity's `id`.

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

Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` controls the starting position: it defaults to 0 and its minimum accepted value is 0. Both must be integers; a `limit` outside the inclusive range 1 through 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION` (HTTP 400).

Unless a workflow in §3 names a different ordering for a computation's internal iteration, list endpoints return rows sorted by `created_at` ascending. Every list response carries `limit`, `offset`, `total_count` and `has_more` inside `meta`, where `total_count` is the number of rows matching the filters before the page window is applied and `has_more` indicates whether rows remain beyond the current window.

### 2.4. Resource Identity, Versioning and Common Properties

Every stored resource carries a server-minted `id`, formatted as a UUID with no type prefix of any kind. Clients never supply an `id`. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded from the logical clock at the moment the row was written.

Most resources additionally carry `updated_at` — the same format, refreshed on every mutation — and `version`, an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row. Two entity types are deliberate exceptions: an `AccountTransaction` and a `RefundApproval` are immutable audit records, and they carry only `id` and `created_at`; neither `updated_at` nor `version` exists on them at all. Where §3 describes a side effect that "bumps the version" of a parent record, it means exactly that the parent's `version` is incremented by 1 and its `updated_at` is refreshed.

Path identifiers are resolved strictly left to right. A request naming several path segments that each carry an id resolves the leftmost first; if that id does not match a stored row the request fails immediately with that entity's not-found error and no further segment is examined. The not-found errors are entity-specific: `ERR_PAYER_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_CREDIT_BALANCE_NOT_FOUND`, `ERR_ROOT_CAUSE_FINDING_NOT_FOUND`, `ERR_REFUND_REQUEST_NOT_FOUND`, `ERR_REFUND_APPROVAL_NOT_FOUND`, `ERR_REFUND_BATCH_NOT_FOUND`, `ERR_CHECK_NOT_FOUND`, `ERR_TAKE_BACK_NOTICE_NOT_FOUND`, `ERR_OFFSET_APPLICATION_NOT_FOUND`, `ERR_MEDICARE_OBLIGATION_NOT_FOUND`, `ERR_ESCHEATMENT_RECORD_NOT_FOUND` and `ERR_COMPLIANCE_REPORT_NOT_FOUND`, all HTTP 404.

The same catalogue applies to foreign keys supplied in a request body rather than in the path. A `primary_payer_id`, `payer_id`, `credit_balance_id`, `refund_request_id`, `refund_batch_id`, `check_disbursement_id` or any member of a `target_account_ids` array that does not resolve to a stored row produces the corresponding not-found error at HTTP 404 — `ERR_PAYER_NOT_FOUND` for a payer, `ERR_ACCOUNT_NOT_FOUND` for an account, `ERR_CREDIT_BALANCE_NOT_FOUND` for a credit balance, `ERR_REFUND_REQUEST_NOT_FOUND` for a refund request, `ERR_REFUND_BATCH_NOT_FOUND` for a batch and `ERR_CHECK_NOT_FOUND` for a check. Body-level resolution is checked on account creation, on ledger posting, on root-cause filing, on refund request creation, on adding a line to a check run, on reissuing a check, on recording a take-back notice, on applying offsets and on opening an unclaimed-property record.

Any request whose body is missing a required field, carries an enum value outside the declared member set, carries a non-integer where an integer is required, carries a negative value in a cents field whose definition forbids one, or supplies an empty `target_account_ids` array is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.5. The Logical Clock

Time in this service is not wall-clock time. The server keeps a single **logical clock**, and every instant it stamps — `posted_at`, `identified_at`, `decided_at`, `issued_at`, `cleared_at`, `applied_at`, `reversed_at`, `received_at`, `due_diligence_sent_at`, `claimed_at`, `reported_at`, `satisfied_at`, `created_at` and `updated_at` — is read from that clock. Every deadline comparison, every aging computation and every dormancy computation in this document is likewise evaluated against the logical clock and never against real time.

At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`. Until it is explicitly moved, that instant is what the service reports and stamps; it never falls back to real wall-clock time. A `SystemAdmin` may reposition the clock at will by supplying a target instant in the `to_iso8601` field, and the clock may be moved forward or backward. Repositioning the clock mutates no entity, but every time-derived computed field — ages, buckets, days elapsed, days late, penalties, dormancy dates — is evaluated against the new instant from that point on. The response reports the resulting instant as `current_utc`.

Where §3 says a value is "recomputed on read", it means the field is derived at response time from the logical clock and the current stored data rather than being frozen at write time. Where §3 says a value is "frozen", it means the value was captured once at a named event and is not re-derived afterwards.

### 2.6. Cents, Whole Days and Rounding

All monetary amounts are integers in cents. There are no fractional cents anywhere in the system, and every stored money field ends in `_cents`. Where a computation produces a non-integer intermediate — a percentage of a reportable amount, a proportional share of a credit, a basis-point fee — the result is rounded half up to the nearest whole cent. Half up means that a value whose fractional part is exactly one half rounds away from zero to the next larger magnitude.

Elapsed time is measured in **whole days, floored**. To compute a whole-day age, take the difference between the later instant and the earlier instant, express it in seconds, divide by 86,400 and discard any fractional part. A duration of twenty-nine days and twenty-three hours is therefore twenty-nine whole days, not thirty. Adding a number of days to an instant means adding that many periods of exactly 86,400 seconds.

Two rounding conventions in this system are order-sensitive and are called out again where they apply: the processing fee on a refund check is rounded once and only then capped, never capped and then rounded; and the administrative fee on a take-back notice is rounded per allocated line and only then summed, never summed and rounded once at the end.

### 2.7. Optimistic Concurrency on Parent Records

Three write operations act on a child resource while depending on a picture of a parent resource that the client read earlier. Each of them requires the client to declare which version of that parent it believes it is working against, and each rejects the write with `ERR_STALE_VERSION` (HTTP 412) when the declaration does not match the parent's current `version`.

- Creating a refund request requires a non-optional `expected_credit_balance_version` field carrying the client's last observed `version` of the target `CreditBalance`. If the credit balance's `version` has advanced since the client read it, the create is rejected with `ERR_STALE_VERSION` at HTTP 412. This check is load-bearing precisely because a credit balance legitimately supports more than one refund request over its life — a rejected request returns the credit to the refundable pool and a fresh request may claim it, and offset applications shrink the outstanding amount underneath — so no state precondition would catch a writer carving a refund out of a credit picture that no longer exists.
- Applying offsets against a take-back notice requires a non-optional `expected_take_back_notice_version` field carrying the client's last observed `version` of that `TakeBackNotice`. A mismatch against the notice's current `version` is rejected with `ERR_STALE_VERSION` at HTTP 412. A notice legitimately accepts repeated offset calls while it is still absorbing its recoupment pool, so a later call would otherwise succeed against a remaining-pool figure the client never saw.
- Locking a check run requires a non-optional `expected_refund_batch_version` field carrying the client's last observed `version` of that `RefundBatch`. A mismatch is rejected with `ERR_STALE_VERSION` at HTTP 412. A batch legitimately cycles between open and locked and accumulates lines in between, so a lock issued against a stale view would freeze a line set the client never inspected.

No other endpoint in this service accepts a version field, and none may be added: everything else is guarded by state preconditions alone.

### 2.8. The Order in Which a Request Is Rejected

A single request can violate several rules at once. The service does not report the first violation it happens to notice; it evaluates rules in a fixed global priority order and returns the error belonging to the **first** rule that fails, ignoring every later rule. The ordering below is normative — a request that both names a non-existent credit balance and carries an illegal enum value fails on existence, not on shape, because existence is checked first. The detailed business meaning of each rule lives in the §3 subsection that owns the workflow; what follows is the ranking.

1. Header presence and role legality — `ERR_UNAUTHENTICATED`.
2. The acting role is authorised for the endpoint — `ERR_FORBIDDEN_ROLE`.
3. Every id in the path resolves, left to right — the entity-specific 404 from §2.4.
4. Every foreign key in the request body resolves — the entity-specific 404 from §2.4.
5. Payer scoping for a `PayerLiaison` — `ERR_PAYER_SCOPE_VIOLATION`. This applies to recording a take-back notice, disputing one, and withdrawing a dispute.
6. Request-body shape and enum legality on every write endpoint, including the restriction that a ledger posting made through the account posting capability may only carry a `txn_type` of `CHARGE`, `PAYMENT` or `CONTRACTUAL_ADJUSTMENT` — `ERR_INVALID_REQUEST`.
7. Pagination bounds on every list endpoint — `ERR_INVALID_PAGINATION`.
8. The credit balance is in the `status` the operation requires — `ERR_CREDIT_BALANCE_INVALID_STATE`. This guards taking a credit into review (which requires `IDENTIFIED`), attributing it (which requires `UNDER_REVIEW`), writing it off (which requires `ATTRIBUTED`) and creating a refund request against it (which requires `ATTRIBUTED`).
9. The refund request is in the approval and disbursement states the operation requires — `ERR_REFUND_REQUEST_INVALID_STATE`. This guards submission (which requires `DRAFT` or `RETURNED_FOR_REVISION`), decision (which requires `SUBMITTED`), cancellation (which requires `DRAFT`, `RETURNED_FOR_REVISION` or a `disbursement_state` of `REISSUE_PENDING`) and adding the request to a check run (which requires `approval_state` `APPROVED` together with `disbursement_state` `NOT_SCHEDULED` or `REISSUE_PENDING`).
10. The check run is in the state the operation requires — `ERR_BATCH_INVALID_STATE`. This guards adding a line (`OPEN`), locking (`OPEN`), unlocking (`LOCKED`), issuing (`LOCKED`) and reissuing a check into a target run (`OPEN`).
11. The check is in the state the operation requires — `ERR_CHECK_INVALID_STATE`. This guards clearing (`ISSUED`), voiding (`ISSUED` or `STALE`), reissuing (a `STALE` check, or a check already `VOIDED` whose owning request sits in `REISSUE_PENDING`) and opening an unclaimed-property record against a check (which requires `STALE`).
12. The take-back notice is in the state the operation requires — `ERR_NOTICE_INVALID_STATE`. Applying offsets and filing a dispute both require `RECEIVED` or `PARTIALLY_APPLIED`; withdrawing a dispute requires `DISPUTED`; a `WITHDRAWN` notice accepts nothing at all.
13. The Medicare obligation is `OPEN` or `LATE` when self-reported — `ERR_OBLIGATION_INVALID_STATE`. An obligation already in `REPORTED`, `REPORTED_LATE` or any satisfied state cannot be reported again.
14. The unclaimed-property record is in the state the operation requires — `ERR_ESCHEATMENT_INVALID_STATE`. Recording due diligence requires `DORMANT`; remitting requires that the record is not already terminal, that is, not `CLAIMED`, `REMITTED` or `EXEMPT`. Note the deliberate gap: a still-`DORMANT` record passes this rule on a remittance attempt and is caught later, at rank 21.
15. The compliance report is `DRAFT` when finalised — `ERR_REPORT_INVALID_STATE`.
16. The transaction targeted for reversal has not already been reversed and is not itself a reversal row — `ERR_TRANSACTION_ALREADY_REVERSED`.
17. The supplied `expected_credit_balance_version`, `expected_take_back_notice_version` or `expected_refund_batch_version` equals the parent's current `version` — `ERR_STALE_VERSION`.
18. Segregation of duties on a refund decision — `ERR_SEGREGATION_OF_DUTIES`.
19. No existing approval on this request already carries the deciding approver's `X-User-ID` — `ERR_DUPLICATE_APPROVER`.
20. No Medicare obligation on the credit balance is `OPEN` or `LATE` when a write-off is attempted — `ERR_MEDICARE_OBLIGATION_OPEN`.
21. The unclaimed-property record has `due_diligence_sent_at` set before any remittance — `ERR_DUE_DILIGENCE_REQUIRED`.
22. The logical clock is at or after the record's `escheat_due_at` when remitting — `ERR_DORMANCY_NOT_ELAPSED`.
23. The logical clock is at or after the record's `due_diligence_open_at` when recording due diligence — `ERR_DUE_DILIGENCE_TOO_EARLY`.
24. The logical clock is at or before the notice's `dispute_deadline_at` when disputing — `ERR_DISPUTE_WINDOW_CLOSED`.
25. Report period ordering — `ERR_INVALID_PERIOD`.
26. Check-run window ordering — `ERR_INVALID_BATCH_WINDOW`.
27. Check-run window non-overlap on the same disbursement channel — `ERR_BATCH_WINDOW_OVERLAP`.
28. Report period separation for the same report type and scope — `ERR_REPORT_PERIOD_CONFLICT`.
29. `payer_code` is unique across all payers — `ERR_DUPLICATE_PAYER_CODE`.
30. `account_number` is unique across all patient accounts — `ERR_DUPLICATE_ACCOUNT_NUMBER`.
31. `batch_number` is unique across all check runs — `ERR_DUPLICATE_BATCH_NUMBER`.
32. `notice_number` is unique within a payer — `ERR_DUPLICATE_NOTICE_NUMBER`.
33. At most one unclaimed-property record exists per check — `ERR_ESCHEATMENT_ALREADY_EXISTS`.
34. The patient account behind the credit balance is `OPEN` when a refund request is created — `ERR_ACCOUNT_NOT_REFUNDABLE`.
35. The named payee bucket is funded — `ERR_PAYEE_TYPE_MISMATCH`.
36. The notice's payer is permitted to file take-backs — `ERR_TAKE_BACK_NOT_PERMITTED`.
37. A ledger posting names a payer exactly when its money came from a payer — `ERR_TRANSACTION_PAYER_REQUIRED`.
38. The requested refund amount clears the minimum refund floor — `ERR_REFUND_BELOW_MINIMUM`.
39. The credit is still economically present on the account — `ERR_CREDIT_ALREADY_CONSUMED`.
40. The requested refund amount fits inside the payee bucket and the outstanding credit — `ERR_REFUND_EXCEEDS_CREDIT`.
41. The deciding approver's claimed signing authority meets the request's required tier — `ERR_APPROVAL_TIER_INSUFFICIENT`.
42. The computed net check amount clears the minimum check floor — `ERR_NET_BELOW_MIN_CHECK`. This applies both to adding a line to a check run and to reissuing a check.
43. The check run holds at least one counted line when locked or issued — `ERR_BATCH_EMPTY`.
44. The offset eligibility filter yields at least one credit balance line — `ERR_NO_ELIGIBLE_CREDIT`.
45. The outstanding credit is within the de-minimis write-off ceiling — `ERR_WRITE_OFF_LIMIT_EXCEEDED`.
46. A returned refund request has not exhausted its revision allowance — `ERR_MAX_REVISIONS_EXCEEDED`.
47. An account being closed carries no open credit liability — `ERR_ACCOUNT_HAS_OPEN_CREDIT`.

Two consequences of this ordering are worth stating outright. Because state checks (ranks 8 through 16) precede the fiscal checks (ranks 38 through 46), a request that is both in the wrong state *and* fiscally impossible reports the state error. Because the stale-version check sits at rank 17, a request carrying a stale parent version but an otherwise valid body reports `ERR_STALE_VERSION` rather than any downstream fiscal complaint — but a request that is *also* in the wrong state reports the state error, because state outranks concurrency.

### 2.9. Cascade Discipline and Derived Balances

Several operations in this system touch four entity layers in a single request. The service treats these as ordered hops and applies them all before responding; a partially applied cascade is never observable. The four canonical chains are: issuing a check run (check line, then refund request, then credit balance, then Medicare obligation); voiding a check (ledger reversal, then refund request, then credit balance, then Medicare obligation); applying offsets (ledger postings, then credit balance recompute, then credit balance status, then Medicare obligation); and remitting unclaimed property (check, then credit balance and its ledger posting). Each hop is described in full in the §3 subsection that owns it, and each hop that mutates a row bumps that row's `version` and refreshes its `updated_at`.

No balance in this system is stored independently of the rows that justify it. An account's `balance_cents` is the sum of `amount_cents` over **all** transactions on that account, reversal rows included — a reversal row carries the exact negation of its target, so a reversed pair sums to zero without either row being deleted. A negative `balance_cents` means the account is in credit. An account's `credit_balance_cents` is the sum of `credit_amount_cents` over the credit balance rows on that account whose `status` is `IDENTIFIED`, `UNDER_REVIEW`, `ATTRIBUTED` or `REFUND_PENDING`; those four statuses constitute open credit liability, and a credit balance in any other status contributes nothing. An account's `last_activity_at` is the latest `posted_at` across the transactions on that account that have not been reversed; it is null when the account has no such transaction.

The same discipline governs the credit balance itself. Its `refunded_cents` is the sum of `gross_amount_cents` over the checks written against it whose `state` is `ISSUED`, `CLEARED`, `STALE`, `REISSUED` or `ESCHEATED` — a `PENDING` or `VOIDED` check contributes nothing. Its `offset_cents` is the sum of `applied_cents` over the offset lines against it whose `state` is `APPLIED`; a `REVERSED` line contributes nothing. Its `outstanding_cents` is `credit_amount_cents` less `refunded_cents` less `offset_cents`. On a take-back notice, `applied_cents` is the sum of `applied_cents` over its offset lines in state `APPLIED`, and `remaining_unapplied_cents` is `total_recoup_cents` less that sum. On a check run, `item_count` is the number of check lines on the run whose `state` is anything other than `VOIDED`, and `total_gross_cents`, `total_fee_cents` and `total_net_cents` are the sums of `gross_amount_cents`, `processing_fee_cents` and `net_check_amount_cents` over those same counted lines.

### 2.10. Window and Period Reservation Semantics

Two resources in this system reserve an interval, and they use deliberately different conventions.

A check run occupies a **half-open** window on its disbursement channel: the interval runs from `cutoff_at` inclusive to `scheduled_run_at` exclusive. Two runs drawing on the same `bank_account_code` may not have intersecting windows while both are alive, where alive means a `state` of `OPEN`, `LOCKED` or `ISSUED`; a `CLOSED` run releases its window. Because the interval is half-open, **touching is allowed**: a new run whose `cutoff_at` is exactly an existing run's `scheduled_run_at`, or whose `scheduled_run_at` is exactly an existing run's `cutoff_at`, does not intersect and is accepted. There is no buffer requirement. An intersecting window is rejected with `ERR_BATCH_WINDOW_OVERLAP` (HTTP 409).

A compliance report occupies a **closed** period with a mandatory buffer: the interval runs from `period_start_at` inclusive to `period_end_at` inclusive, and separation is enforced against every existing report — whether `DRAFT` or `FINALIZED` — that shares both the same `report_type` and the same `scope_code`. The new report is acceptable only if its `period_start_at` is at or after the existing report's `period_end_at` plus seven days, or its `period_end_at` is at or before the existing report's `period_start_at` minus seven days. Because the interval is closed and a seven-day gap is required, **touching is rejected**: adjacency is forbidden, and anything closer than a full seven-day separation is rejected with `ERR_REPORT_PERIOD_CONFLICT` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Payers, Patient Accounts and the Ledger Spine

Before anything can go wrong financially, the reference data has to exist. A `SystemAdmin` registers each payer organisation with a display `name`, a short external `payer_code` and a `payer_type` drawn from `MEDICARE`, `MEDICAID`, `COMMERCIAL`, `TRICARE` and `SELF_PAY`. The `payer_code` must be between 2 and 16 characters and must be globally unique; a collision is rejected with `ERR_DUPLICATE_PAYER_CODE`. Two optional switches shape the payer's later behaviour: `take_back_allowed` decides whether this payer may ever file a recoupment notice and defaults to true, and `refund_remit_days` records the contractual number of days the hospital has to remit a refund to this payer and defaults to 30. Payers can be listed and filtered by `payer_type`.

Patient accounts are opened by a `SystemAdmin` or a `CreditAnalyst`. Each carries a globally unique hospital `account_number` — a duplicate is rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER` — plus an `mrn` medical record number, a `patient_name` for the patient or guarantor, a `guarantor_state_code` of `CA`, `TX`, `NY` or `FL`, a `primary_payer_id` naming the payer of record, and a `financial_class` of `INPATIENT`, `OUTPATIENT` or `EMERGENCY`. A `discharge_date` may be supplied and may be omitted. A newly opened account starts with `balance_cents` and `credit_balance_cents` at 0 and a `status` of `OPEN`. Accounts can be listed and filtered by `primary_payer_id` and by `status`.

Money moves through the account as ledger postings. A `CreditAnalyst` or `SystemAdmin` may post a `CHARGE`, a `PAYMENT` or a `CONTRACTUAL_ADJUSTMENT`; those three are the only `txn_type` values the posting capability accepts, and anything else — `REFUND_DISBURSEMENT`, `TAKE_BACK_OFFSET`, `ESCHEAT_REMITTANCE` or `REVERSAL` — is rejected with `ERR_INVALID_REQUEST` because those four rows are written only by the system as cascade side effects, with `REVERSAL` additionally written by the explicit reversal capability described below. A posting carries a signed `amount_cents`, a `source` of `PATIENT`, `PAYER` or `SYSTEM`, an optional `effective_at` service date and an optional free-text `remark`. Sign convention is fixed: `CHARGE`, `REFUND_DISBURSEMENT`, `TAKE_BACK_OFFSET` and `ESCHEAT_REMITTANCE` rows carry positive amounts, `PAYMENT` and `CONTRACTUAL_ADJUSTMENT` rows carry negative amounts, and a `REVERSAL` row carries the exact negation of the row it reverses. When `effective_at` is omitted it defaults to the posting's `posted_at`, which is itself stamped from the logical clock. The `account_id` on the posting is taken from the account named in the path, never from the body.

A `payer_id` on a posting is required exactly when the money came from a payer. If `source` is `PAYER` and `payer_id` is absent, or if `payer_id` is supplied while `source` is anything other than `PAYER`, the posting is rejected with `ERR_TRANSACTION_PAYER_REQUIRED` (HTTP 422). Every accepted posting recomputes the owning account's `balance_cents` and `last_activity_at` and bumps the account's `version` by 1.

Mis-postings are corrected by reversal, never by deletion. A `CreditAnalyst` may reverse a stored transaction, which writes a new `REVERSAL` row whose `amount_cents` is the exact negation of the target's, whose `reversal_of_transaction_id` points at the target, and which may carry its own `remark`. The target's `is_reversed` flag becomes true — that flag is true precisely when some reversal row names the target — and the account's `balance_cents` is recomputed. A transaction that already carries a reversal, or a transaction that is itself a `REVERSAL` row, cannot be reversed: the attempt fails with `ERR_TRANSACTION_ALREADY_REVERSED`. Reversal rows are immutable audit records and, like approval decisions, carry only an `id` and a `created_at`. Ledger transactions can be listed and filtered by `account_id`, by `payer_id`, by `reversal_of_transaction_id` — which is how the reversal of a given posting is located — and by `txn_type`.

An account's `status` is moved by a `SystemAdmin` alone, by supplying the target `status`. An `OPEN` account may move to `BAD_DEBT`, and it may move to `CLOSED` only when its `credit_balance_cents` is exactly 0 — an account still carrying open credit liability is refused with `ERR_ACCOUNT_HAS_OPEN_CREDIT`. A `BAD_DEBT` account may be returned to `OPEN`, at which point it is refundable again. There is no path back from `CLOSED`. Both `CLOSED` and `BAD_DEBT` are non-refundable: once an account is in either, every later attempt to prepare a refund request against a credit balance on that account fails with `ERR_ACCOUNT_NOT_REFUNDABLE`. Each accepted status move bumps the account's `version` by 1.

### 3.2. Finding the Credits: the Identification Sweep and Aging

A `CreditAnalyst` initiates the identification sweep, optionally narrowing it with an `account_ids` array; when that array is omitted the sweep considers every account in the system. An account is a candidate only when all four of the following hold, evaluated in this order: it is named in `account_ids` or `account_ids` was omitted; its `status` is `OPEN` or `BAD_DEBT`, so a `CLOSED` account is skipped even when it is in credit; its `balance_cents` is at or below negative one cent, which is to say the account is genuinely in credit by at least one cent; and no credit balance already exists on that account whose `status` is `IDENTIFIED`, `UNDER_REVIEW`, `ATTRIBUTED`, `REFUND_PENDING` or `REFUNDED`. That last condition is what stops the sweep from double-counting the same overpayment on every run — note that it also excludes an account whose credit has been refunded but is not yet escheated, while an account whose only credit balance is `RESOLVED_BY_OFFSET`, `ESCHEATED` or `WRITTEN_OFF` becomes eligible again.

Candidates are processed in ascending `created_at` order so the sweep is deterministic. For each candidate the service creates one credit balance row whose `account_id` is the account, whose `payer_id` is copied from that account's `primary_payer_id`, whose `credit_amount_cents` is the magnitude of the account's negative `balance_cents` frozen at this moment — the sign is inverted, so an account sitting at negative twenty thousand cents produces a credit amount of twenty thousand cents — whose `identified_at` is the current logical clock instant, and whose `status` is `IDENTIFIED`. The sweep then recomputes `credit_balance_cents` on each swept account. Its response reports `identified_count`, the number of rows created; `credit_balance_ids`, their ids in sweep order; and `skipped_account_count`, the number of accounts explicitly named in `account_ids` that failed to qualify as candidates. When `account_ids` was omitted, `skipped_account_count` is 0.

From the instant of identification, the credit ages. Whenever a credit balance is read — individually, in a list, or during the nightly checkpoint — its `aging_days` is recomputed as the whole floored days from `identified_at` to the logical clock, and its `aging_bucket` is derived from that count by four edges: `D0_30` when `aging_days` is at most 30, `D31_60` when it is at most 60, `D61_90` when it is at most 90, `D91_180` when it is at most 180, and `OVER_180` beyond that. The edges are inclusive on the lower bucket, so a credit exactly 30 whole days old is still `D0_30` and one 31 whole days old is `D31_60`; a credit exactly 180 whole days old is still `D91_180` and one 181 whole days old is `OVER_180`.

The credit balance also exposes `attribution_method` and `attribution`, both null until attribution runs; `patient_portion_cents` and `payer_portion_cents`, both 0 until then; the derived `refunded_cents`, `offset_cents` and `outstanding_cents` described in §2.9; and `root_cause_confirmed`, a flag that is true exactly when at least one root-cause finding on this credit balance has `confirmed` set to true. Lists of credit balances may be filtered by `account_id`, by `payer_id`, by `status` and by `aging_bucket`.

### 3.3. Explaining the Overpayment: Root-Cause Findings

A credit balance without an explanation is an audit finding waiting to happen, so analysts document why the money arrived. A `CreditAnalyst` files a finding against a credit balance by naming the `credit_balance_id`, choosing a `cause_code` from `DUPLICATE_PAYMENT`, `CONTRACTUAL_UNDER_ADJUSTMENT`, `WRONG_ACCOUNT_POSTING`, `COB_PRIMARY_SECONDARY`, `ESTIMATE_OVERCOLLECTION` and `RETRO_ELIGIBILITY_CHANGE`, choosing a `corrective_action` from `REPOST_TRANSACTION`, `UPDATE_CONTRACT_TERMS`, `STAFF_RETRAINING`, `PAYER_ESCALATION` and `NONE`, and writing a `narrative`. Two fields are optional: `evidence_transaction_ids`, an array of ledger transaction ids cited as proof, which defaults to an empty array; and `confirmed`, a boolean asserting that the cause is proven rather than suspected, which defaults to false. The filing analyst's `X-User-ID` is stamped onto the finding as `analyst_user_id`.

Filing a finding has a consequence beyond documentation. It recomputes the owning credit balance's `root_cause_confirmed` and bumps that credit balance's `version` by 1 — which matters twice over. It matters for money, because an unconfirmed root cause escalates the approval tier of any refund carved out of this credit (see §3.5). And it matters for concurrency, because a client that read the credit balance before filing the finding is now holding a stale `version` and will be refused when it tries to create a refund request. Findings can be listed and filtered by `credit_balance_id`, by `cause_code` and by `confirmed`.

### 3.4. Attribution: Deciding Whose Money It Is

A newly identified credit sits in `IDENTIFIED` until an analyst picks it up. Taking it into review moves the credit balance `IDENTIFIED → UNDER_REVIEW` and bumps its `version` by 1; a credit balance in any other status is refused with `ERR_CREDIT_BALANCE_INVALID_STATE`.

Attribution is the decision that splits the credit between the patient and the payer, and it moves the credit balance `UNDER_REVIEW → ATTRIBUTED`. The analyst chooses an `attribution_method`, which must be either `PROPORTIONAL` or `REVERSE_CHRONOLOGICAL`; the accepted value is stored on the credit balance, and the run bumps its `version` by 1.

Both methods look at the same input set. Take every ledger transaction on the credit balance's account whose `txn_type` is `PAYMENT`, whose `is_reversed` is false, whose `reversal_of_transaction_id` is null — a reversal row is never itself treated as a payment — and whose `posted_at` is at or before the credit balance's `identified_at`, that upper bound being inclusive. Because payments carry negative amounts, each qualifying payment contributes its magnitude, that is, its `amount_cents` with the sign dropped. Let the total paid be the sum of those magnitudes and let the credit be the credit balance's `credit_amount_cents`.

If the total paid is zero — no qualifying payment exists at all — then `patient_portion_cents` is 0, `payer_portion_cents` is 0, and `attribution` is `UNDETERMINED`. Otherwise the chosen method decides the split:

- Under `PROPORTIONAL`, sum the magnitudes of the qualifying payments whose `source` is `PATIENT`. The patient slice is the credit multiplied by that patient-paid sum, divided by the total paid, rounded half up to a whole cent. The payer slice is then the credit minus the patient slice, so the payer bucket absorbs the residual cent and the two portions always sum exactly to `credit_amount_cents`. Whenever both sources contributed money, both buckets receive a slice.
- Under `REVERSE_CHRONOLOGICAL`, sort the qualifying payments by `posted_at` descending, breaking ties by `created_at` descending, and unwind the credit against them newest first. Start with the whole credit remaining and both portions at 0. For each payment in that order, take the smaller of the remaining credit and that payment's magnitude, add the taken amount to `patient_portion_cents` when the payment's `source` is `PATIENT` and to `payer_portion_cents` otherwise, subtract the taken amount from the remaining credit, and stop as soon as the remaining credit reaches 0. A single recent payment large enough to cover the whole credit therefore takes the entire attribution and leaves the other bucket at 0 — which is exactly how this method differs from the proportional one on an identical ledger.

Once the two portions are known, the classification is the same under both methods: `attribution` is `SPLIT` when both portions are strictly positive, `PATIENT` when only the patient portion is strictly positive, and `PAYER` otherwise.

Attribution carries one further consequence, and it is the trigger for the entire compliance track described in §3.10. If the credit balance's payer is of `payer_type` `MEDICARE` and the computed `payer_portion_cents` is strictly greater than 0, the same call creates a Medicare repayment obligation in state `OPEN`, copying the credit balance's `identified_at` onto the obligation, freezing `reportable_amount_cents` at the computed `payer_portion_cents`, and setting `due_at` to sixty days after `identified_at`. No obligation is created for any other payer type, and none is created when the payer portion is 0.

A credit balance may also leave the workflow without ever being refunded. A `ComplianceOfficer` may write off a de-minimis credit, moving it `ATTRIBUTED → WRITTEN_OFF` with a supplied `reason_code` and bumping its `version` by 1. Two guards apply. The outstanding credit must be small: `outstanding_cents` must be at most 1,000 cents — ten dollars — or the attempt fails with `ERR_WRITE_OFF_LIMIT_EXCEEDED`. And no Medicare obligation on that credit balance may still be unresolved: if one sits in `OPEN` or `LATE`, the write-off is refused with `ERR_MEDICARE_OBLIGATION_OPEN`, because a federal overpayment cannot be made to disappear by an internal accounting entry. An obligation that has already been self-reported is a different matter: a write-off carries a `REPORTED` obligation to `SATISFIED` and a `REPORTED_LATE` obligation to `SATISFIED_LATE`, in both cases recording a `satisfaction_mode` of `WRITE_OFF` and a `satisfied_at`. `WRITTEN_OFF` is terminal.

### 3.5. Preparing a Refund Request

A `CreditAnalyst` prepares a refund by naming the `credit_balance_id`, the `requested_amount_cents` in gross cents, a `payee_type` of `PATIENT` or `PAYER` identifying which attribution bucket funds the refund, the `payee_name` and `payee_address_line` to be printed on the check, a `payee_state_code` of `CA`, `TX`, `NY` or `FL` recording the payee's escheat jurisdiction, and the `expected_credit_balance_version` demanded by §2.7. The preparing analyst's `X-User-ID` is stamped onto the request as `prepared_by_user_id`. A new request starts with an `approval_state` of `DRAFT`, a `disbursement_state` of `NOT_SCHEDULED`, `approved_amount_cents` at 0, `approvals_received` at 0 and `revision_count` at 0.

Five business guards stand between the analyst and a created request, and they are evaluated in the global order of §2.8. The credit balance must be `ATTRIBUTED` — otherwise `ERR_CREDIT_BALANCE_INVALID_STATE`. The account behind it must be `OPEN` — a `CLOSED` or `BAD_DEBT` account yields `ERR_ACCOUNT_NOT_REFUNDABLE`. The named bucket must be funded: `PATIENT` requires `patient_portion_cents` strictly greater than 0 and `PAYER` requires `payer_portion_cents` strictly greater than 0, and naming an empty bucket yields `ERR_PAYEE_TYPE_MISMATCH` (HTTP 422). The `requested_amount_cents` must be at least 100 cents — one dollar — or the request is refused with `ERR_REFUND_BELOW_MINIMUM` (HTTP 422). And the credit must still be economically present: the account's `balance_cents` must be strictly negative at the moment of creation. This last guard exists because a later `CHARGE` can consume an overpayment while the credit balance row still reads `ATTRIBUTED` with a positive `outstanding_cents`; when the account has been brought back to zero or above, the attempt is rejected with `ERR_CREDIT_ALREADY_CONSUMED` (HTTP 409).

A sixth guard bounds the amount from above. The `requested_amount_cents` may not exceed the smaller of the payee bucket's capacity and the credit balance's `outstanding_cents`, where bucket capacity means `patient_portion_cents` when `payee_type` is `PATIENT` and `payer_portion_cents` when it is `PAYER`. Exceeding that ceiling is rejected with `ERR_REFUND_EXCEEDS_CREDIT` (HTTP 422). Note the ordering consequence: the below-minimum check at rank 38 and the already-consumed check at rank 39 both precede this ceiling check at rank 40, so a request that is simultaneously too small and too large reports the below-minimum error.

When all guards pass, the request is created, the owning credit balance moves `ATTRIBUTED → REFUND_PENDING`, and the credit balance's `version` is bumped by 1 — which immediately invalidates any other client's cached `expected_credit_balance_version` for that credit.

### 3.6. How Much Signing Authority a Refund Needs

The same computation runs twice in a request's life: once when the request is first created, and again each time it is submitted for approval. Both runs overwrite `required_approval_tier` and `required_approval_count`, so a request that sat in draft while its credit aged past a threshold, or while an analyst confirmed a root cause, can legitimately need a different tier on submission than it needed on creation.

The computation reads five things: the request's own `requested_amount_cents`; the owning credit balance's `aging_days` evaluated at the moment of this call; the request's `payee_type`; the `payer_type` of the payer on that credit balance; and the credit balance's `root_cause_confirmed` flag, likewise at call time.

A base tier comes from the amount alone. A request of at most 25,000 cents — two hundred and fifty dollars — is base tier 1. A request above 25,000 cents and at most 250,000 cents — two thousand five hundred dollars — is base tier 2. Anything above 250,000 cents is base tier 3.

Three independent escalations are then counted, each adding one. The first applies when the credit balance's payer is of type `MEDICARE` or `MEDICAID`. The second applies when the credit balance's `aging_days` is at least 181 — that is, when the credit has aged into the `OVER_180` bucket. The third applies when `root_cause_confirmed` is false, since paying out money whose cause is still unexplained warrants a second look.

One de-escalation is counted, worth one, and only one condition triggers it: the `payee_type` is `PATIENT` **and** `requested_amount_cents` is at most 5,000 cents — fifty dollars. Small patient refunds are routine and are allowed to shed a level of escalation.

The required tier is then the base tier adjusted by escalations and de-escalation, floored at the base tier and capped at 3. Precisely: take the base tier plus the escalation count minus the de-escalation count; if that adjusted figure is below the base tier, use the base tier instead; then if the result exceeds 3, use 3. The inner floor is a floor, not a tie-break — de-escalation can never push a request below the tier its amount alone demands, so a fifty-dollar patient refund on a fully documented commercial credit stays at tier 1 rather than dropping to zero. Finally, `required_approval_count` is 2 when `required_approval_tier` is 3, and 1 in every other case.

### 3.7. Submission, Decision and the Revision Cycle

Submitting a request moves its `approval_state` from `DRAFT` to `SUBMITTED`, or from `RETURNED_FOR_REVISION` back to `SUBMITTED`, and re-runs the tier computation of §3.6. Re-submission after a return is bounded: the request's `revision_count` must be at most 2 at the moment of re-submission, and a request that has already been sent back and revised more than that is refused with `ERR_MAX_REVISIONS_EXCEEDED` (HTTP 409). Submitting from any other approval state fails with `ERR_REFUND_REQUEST_INVALID_STATE`.

Only a `RefundApprover` decides, and only on a `SUBMITTED` request. The decision names a `decision` of `APPROVED`, `REJECTED` or `RETURNED`, an `approver_tier` stating the signing authority the approver claims (an integer from 1 to 3), and an optional `note`. Every decision — approval, rejection or return alike — writes an immutable approval record stamped with the deciding approver's `X-User-ID` as `approver_user_id`, the `refund_request_id` taken from the path, the supplied `approver_tier`, `decision` and `note`, and a `decided_at` read from the logical clock. The request's `last_decision_user_id` is updated to that same operator identifier. Approval records carry only an `id` and a `created_at`; they have no `version` and no `updated_at`, and they can be listed and filtered by `refund_request_id` and by `decision`.

Three guards protect the decision, and their relative order matters. Segregation of duties comes first: the deciding approver's `X-User-ID` must differ from the request's `prepared_by_user_id`, and an approver deciding on its own preparation is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Duplicate approval comes second: no approval record already on this request may carry the deciding approver's `X-User-ID`, so a tier-3 request genuinely needs two distinct human beings, and a second decision from the same operator is refused with `ERR_DUPLICATE_APPROVER` (HTTP 409). Signing authority comes last, and applies only to approvals: the supplied `approver_tier` must be at least the request's `required_approval_tier`, and a claim below it is refused with `ERR_APPROVAL_TIER_INSUFFICIENT` (HTTP 403). Because segregation and duplication outrank the tier check, an approver who both prepared the request and claims too low a tier is told about segregation of duties.

What an approval does depends on how many are still needed. When `required_approval_count` is 1, or when it is 2 and this approval brings `approvals_received` plus one to at least 2, the approval completes the request: `approval_state` moves `SUBMITTED → APPROVED` and `approved_amount_cents` is set equal to `requested_amount_cents`. When `required_approval_count` is 2 and this approval is only the first — that is, `approvals_received` plus one is still below 2 — the request stays in `SUBMITTED`, `approvals_received` becomes 1, and the approval record is written all the same. This self-loop is deliberate: on a tier-3 request the first signature is recorded but advances nothing, and `approved_amount_cents` stays at 0 until the second signature lands. In general, `approvals_received` is the count of approval records on the request whose `decision` is `APPROVED`, and `approved_amount_cents` is `requested_amount_cents` once and only once the request reaches `APPROVED`, and 0 in every other approval state.

A rejection moves the request `SUBMITTED → REJECTED`, which is terminal, and hands the credit back: the owning credit balance moves `REFUND_PENDING → ATTRIBUTED` and its `version` is bumped by 1, provided no other refund request on that same credit balance is sitting in `SUBMITTED` or `APPROVED`. A return moves the request `SUBMITTED → RETURNED_FOR_REVISION`, increments `revision_count` by 1, and — unlike a rejection — leaves the owning credit balance in `REFUND_PENDING`, because the analyst is expected to fix and resubmit rather than release the credit.

Cancellation is the analyst's own exit. A request in `DRAFT` or `RETURNED_FOR_REVISION` may be cancelled with an optional `reason`, moving `approval_state` to `CANCELLED` and returning the owning credit balance `REFUND_PENDING → ATTRIBUTED` under the same no-other-live-request condition. Cancellation has a second, quite different meaning once money has already moved: a request whose `approval_state` is `APPROVED` and whose `disbursement_state` is `REISSUE_PENDING` — an approved refund whose check was voided and never replaced — is cancelled by moving `disbursement_state` `REISSUE_PENDING → VOID_CLOSED`, again returning the credit balance to `ATTRIBUTED`. `CANCELLED` and `VOID_CLOSED` are both terminal. Cancelling from any other combination fails with `ERR_REFUND_REQUEST_INVALID_STATE`. Refund requests can be listed and filtered by `credit_balance_id`, by `approval_state` and by `disbursement_state`, independently on either dimension.

### 3.8. Check Runs: Assembling, Locking and Issuing

Treasury pays approved refunds in runs. A `DisbursementOfficer` opens a run with a globally unique `batch_number` — a collision is `ERR_DUPLICATE_BATCH_NUMBER` — a `bank_account_code` of `OPERATING`, `TRUST` or `ESCROW` naming the disbursement channel it draws on, a `cutoff_at` and a `scheduled_run_at`. The `cutoff_at` must be strictly before the `scheduled_run_at`, or the run is refused with `ERR_INVALID_BATCH_WINDOW` (HTTP 422); the two instants then bound the half-open occupation window on that channel described in §2.10, and `scheduled_run_at` doubles as the intended issue instant. A new run opens in `state` `OPEN` with `item_count`, `total_gross_cents`, `total_fee_cents` and `total_net_cents` all at 0. Runs can be listed and filtered by `state` and by `bank_account_code`.

Adding a line means naming a `refund_request_id`. The request must be `APPROVED` on the approval dimension and either `NOT_SCHEDULED` or `REISSUE_PENDING` on the disbursement dimension, and the run must be `OPEN`. A line is a check row created in `state` `PENDING`, carrying the `refund_request_id`, the `refund_batch_id` of the run, a `payee_state_code` copied from the refund request, and a `gross_amount_cents` frozen at the request's `approved_amount_cents` as of this moment. Its `check_number`, `issued_at`, `cleared_at` and `stale_at` are all null while the run is `OPEN` or `LOCKED`, its `reissue_of_disbursement_id` is null unless it replaces a predecessor, and its `void_reason` is null unless it is voided. Adding a line moves the request `NOT_SCHEDULED → BATCHED` or `REISSUE_PENDING → BATCHED`, recomputes the run's four totals, and bumps the run's `version` by 1.

The fee on that line is computed as the line is created, and the evaluation order is pinned because it looks circular otherwise. **Step one selects the band, keyed on the gross amount only.** If `gross_amount_cents` is at most 5,000 cents, the rate is zero basis points and the flat component is 0 cents. If it is above 5,000 and at most 50,000 cents, the rate is 150 basis points — one and a half percent — and the flat component is 100 cents. Above 50,000 cents the rate drops to 75 basis points — three quarters of one percent — and the flat component rises to 500 cents. **Step two computes the fee: multiply the gross by the band's basis points, divide by 10,000, round that product half up to a whole cent, add the band's flat component, and then cap the result at 2,500 cents.** Rounding happens once, before the cap, never after it. **Step three sets the net:** `net_check_amount_cents` is `gross_amount_cents` minus `processing_fee_cents`. **Step four is a floor guard:** if the net would fall below 200 cents, the line is refused with `ERR_NET_BELOW_MIN_CHECK` (HTTP 422). Do not iterate to a fixed point and do not re-band on the net — a gross of 5,001 cents is banded at 150 basis points and nets less than a gross of exactly 5,000 cents, and that inversion is intended, not a defect. The same four steps and the same floor guard apply when a replacement check is cut for a stale or voided predecessor.

Freezing a run is a two-part discipline. Locking moves it `OPEN → LOCKED`, requires at least one counted line — an empty run is refused with `ERR_BATCH_EMPTY` (HTTP 409) — requires the `expected_refund_batch_version` of §2.7, and bumps the run's `version` by 1. After locking, no further lines may be added. Unlocking moves it `LOCKED → OPEN` again, takes no body at all, bumps the `version` by 1 and reopens the line set; this revert edge is what makes the lock's stale-version guard necessary in the first place.

Issuing is the single largest cascade in the system, and it runs only on a `LOCKED` run holding at least one counted line; an empty run is again `ERR_BATCH_EMPTY`, and a run in any other state is `ERR_BATCH_INVALID_STATE`. The officer supplies a `starting_check_number`. The run itself moves `LOCKED → ISSUED` and its `version` is bumped by 1, and then four hops fire in order.

- **Hop 1 — the checks.** Every `PENDING` check line in the run moves `PENDING → ISSUED`. Check numbers are assigned sequentially beginning at `starting_check_number`, handed out in ascending `created_at` order over the lines, and written to `check_number`. Each issued check takes an `issued_at` from the logical clock and a `stale_at` of exactly 180 days after its `issued_at`.
- **Hop 2 — the requests.** Each issued check drives its owning refund request `BATCHED → ISSUED` on the disbursement dimension.
- **Hop 3 — the ledger and the credit.** Each of those request transitions posts a `REFUND_DISBURSEMENT` ledger row of positive `gross_amount_cents` on the credit balance's account, then recomputes that credit balance's `refunded_cents` and `outstanding_cents`. When the recomputed `outstanding_cents` reaches 0, the credit balance moves `REFUND_PENDING → REFUNDED` and its `version` is bumped by 1.
- **Hop 4 — the obligation.** Every credit balance that reaches `REFUNDED` settles any Medicare repayment obligation attached to it. An obligation in `OPEN` or `REPORTED` moves to `SATISFIED`; an obligation in `LATE` or `REPORTED_LATE` moves to `SATISFIED_LATE` with its `penalty_cents` recomputed at satisfaction. In every case `satisfied_at` is stamped from the logical clock and `satisfaction_mode` is set to `REFUND_CHECK`.

### 3.9. The Life of an Issued Check

An issued check faces a three-way fork, and the three branches have deliberately different consequences.

**Branch A — it clears.** A `DisbursementOfficer` records that the bank paid it. The check moves `ISSUED → CLEARED` with `cleared_at` stamped from the logical clock, and the owning refund request moves `ISSUED → CLEARED` on the disbursement dimension. No ledger movement occurs and the credit stays consumed. `CLEARED` is terminal for the check. Clearing anything other than an `ISSUED` check fails with `ERR_CHECK_INVALID_STATE`.

**Branch B — it is voided.** A `DisbursementOfficer` may void a check that is `ISSUED` or `STALE`, supplying a `void_reason` of `STALE_DATED`, `WRONG_PAYEE`, `BATCH_ERROR` or `PAYER_REQUEST`; any other value is `ERR_INVALID_REQUEST`, and voiding a check in any other state is `ERR_CHECK_INVALID_STATE`. The check moves to `VOIDED` with its `void_reason` recorded, and the full four-hop compensation of branch A's ledger effects runs. Hop 1 posts a `REVERSAL` ledger row whose `reversal_of_transaction_id` names the check's original `REFUND_DISBURSEMENT` posting and whose `amount_cents` is that posting's exact negation. Hop 2 moves the owning refund request `ISSUED → REISSUE_PENDING` on the disbursement dimension. Hop 3 recomputes the credit balance's `refunded_cents` — the voided check has left the counted set — and its `outstanding_cents`, moves it `REFUNDED → REFUND_PENDING` and bumps its `version` by 1. Hop 4 reopens the Medicare obligation: an obligation in `SATISFIED` returns to `OPEN` when the logical clock is at or before its `due_at` and to `LATE` when the clock is past `due_at`; an obligation in `SATISFIED_LATE` returns to `LATE` unconditionally. In all three cases `satisfied_at` and `satisfaction_mode` are cleared and `days_elapsed`, `days_late` and `penalty_cents` are recomputed against the current logical clock. Separately, any unclaimed-property record on this check that is still `DORMANT` moves to `EXEMPT`, because the funds have gone back to the credit balance instead of escheating.

**Branch C — it goes stale.** Nothing is called; time passes. The nightly checkpoint moves an `ISSUED` check to `STALE` once the logical clock reaches or passes its `stale_at`. There is no ledger movement and no compensation: the money is still notionally paid out, but the instrument has expired and the check has become escheat-eligible.

A `STALE` check has three exits of its own. It may be voided with a `void_reason` of `STALE_DATED`, which runs exactly the same four-hop compensation chain as the void of an `ISSUED` check. It may be reissued. Or it may be escheated, which is the subject of §3.12.

Reissuing cuts a replacement line into an open run. The `DisbursementOfficer` names the target `refund_batch_id`, which must be a run in `state` `OPEN` — otherwise `ERR_BATCH_INVALID_STATE`. The predecessor must be a `STALE` check, or a check already `VOIDED` whose owning request sits in `REISSUE_PENDING`; anything else is `ERR_CHECK_INVALID_STATE`. A successor check row is created with `reissue_of_disbursement_id` pointing at the predecessor, its fee and net recomputed by the four pinned steps of §3.8 (and subject to the same `ERR_NET_BELOW_MIN_CHECK` floor guard), and the owning refund request moves `REISSUE_PENDING → BATCHED` on the disbursement dimension so the cycle `BATCHED → ISSUED → REISSUE_PENDING → BATCHED` can run again. A predecessor that was `STALE` moves `STALE → REISSUED`, which is terminal for it. Reissue bumps the target run's `version` by 1. If an unclaimed-property record on the predecessor had already reached `DUE_DILIGENCE_SENT`, it moves to `CLAIMED` with `claimed_at` stamped and `remitted_amount_cents` left at 0 — the payee turned up, so nothing escheats. Checks can be listed and filtered by `refund_request_id`, by `refund_batch_id`, by `reissue_of_disbursement_id` and by `state`.

### 3.10. Payer Take-Backs, Disputes and the Offset Waterfall

Payers do not always wait for a refund check. A `PayerLiaison` records a recoupment demand as a take-back notice carrying its own `payer_id` — which must equal the liaison's `X-User-ID`, or the request is `ERR_PAYER_SCOPE_VIOLATION` — a `notice_number` that must be unique within that payer (a collision is `ERR_DUPLICATE_NOTICE_NUMBER`), a `total_recoup_cents` naming the amount the payer intends to recover, and an optional `admin_fee_cents` recording an administrative fee the payer withholds, defaulting to 0. The payer must be permitted to file take-backs at all: a payer whose `take_back_allowed` is false is refused with `ERR_TAKE_BACK_NOT_PERMITTED` (HTTP 422). The notice is stamped with a `received_at` from the logical clock, given a `dispute_deadline_at` exactly 45 days after `received_at`, and opened in `state` `RECEIVED` with `applied_cents` at 0.

Working a notice down is the analyst's job. A `CreditAnalyst` applies the notice against a set of accounts by supplying a non-empty `target_account_ids` array and the `expected_take_back_notice_version` demanded by §2.7. The notice must be `RECEIVED` or `PARTIALLY_APPLIED`; a `DISPUTED`, `FULLY_APPLIED` or `WITHDRAWN` notice refuses the call with `ERR_NOTICE_INVALID_STATE`.

Eligibility is a strict filter. A credit balance qualifies for this waterfall only when its `account_id` is among the named `target_account_ids`, its `payer_id` equals the notice's `payer_id`, its `status` is `ATTRIBUTED` or `REFUND_PENDING`, its `payer_portion_cents` is strictly greater than 0 and its `outstanding_cents` is strictly greater than 0. If no credit balance passes that filter, the call is refused with `ERR_NO_ELIGIBLE_CREDIT` (HTTP 422).

Qualifying credits are then consumed oldest first: sort them by `identified_at` ascending, breaking ties by `created_at` ascending. Start with a pool equal to the notice's `remaining_unapplied_cents`. Walk the sorted credits in order; stop as soon as the pool is exhausted. For each credit, its capacity is the smaller of its `payer_portion_cents` and its `outstanding_cents`, and the line amount is the smaller of the remaining pool and that capacity. A line amount of 0 is skipped entirely — no zero-cent rows are ever written — and otherwise the line is recorded and the pool is reduced by the line amount. Let the applied total be the sum of the line amounts actually recorded.

The notice's administrative fee is then prorated across those lines, and the order of operations is pinned. **Round per line, then sum.** For each line, its `admin_fee_share_cents` is the notice's `admin_fee_cents` multiplied by that line's `applied_cents`, divided by the applied total, rounded half up to a whole cent. Take the residual — the notice's `admin_fee_cents` minus the sum of the per-line shares just computed — and add it to the **last** line in waterfall order. The shares therefore always sum to `admin_fee_cents` exactly. Summing first and rounding once at the end is explicitly wrong here and produces different per-line figures.

Each recorded line becomes an offset application. Its `take_back_notice_id` is the notice from the path, its `account_id` and `credit_balance_id` name the credit consumed, its `applied_cents` and `admin_fee_share_cents` are as computed, its `sequence` is a 1-based waterfall position that continues monotonically from the notice's highest existing sequence — the first line of a second call to the same notice takes the next number after the last line of the first call — its `applied_at` is the logical clock, its `reversed_at` is null and its `state` is `APPLIED`. Each line also posts a ledger row of `txn_type` `TAKE_BACK_OFFSET` with `source` `PAYER`, the notice's `payer_id`, a positive `amount_cents` equal to the line's `applied_cents`, on the credit balance's account; that posting's id is stored on the line as `posted_transaction_id`.

Four hops then follow from the postings. Hop 1 is the ledger rows just described. Hop 2 recomputes each touched credit balance's `offset_cents` and `outstanding_cents`. Hop 3 moves any credit balance whose recomputed `outstanding_cents` reaches 0 from `ATTRIBUTED` to `RESOLVED_BY_OFFSET`, bumping its `version` by 1. Hop 4 settles the Medicare obligation on any such credit balance: an obligation in `OPEN`, `LATE` or `REPORTED` moves to `SATISFIED_BY_OFFSET` with `satisfied_at` stamped and `satisfaction_mode` set to `OFFSET`; an obligation that was `LATE` retains its accrued `penalty_cents`. Finally the notice's own `version` is bumped by 1 and it steps forward: it becomes `PARTIALLY_APPLIED` when `remaining_unapplied_cents` after the call is still strictly greater than 0, and `FULLY_APPLIED` when that figure reaches exactly 0. A `PARTIALLY_APPLIED` notice that is worked down to 0 by a later call likewise becomes `FULLY_APPLIED`.

Offset lines can be undone. A `CreditAnalyst` reverses one line at a time with an optional `reason`, and the line must be in `state` `APPLIED` for the reversal to proceed. Reversal moves the line `APPLIED → REVERSED` and stamps `reversed_at`. Hop 1 posts a `REVERSAL` ledger row negating that line's `TAKE_BACK_OFFSET` posting exactly. Hop 2 recomputes the owning credit balance's `offset_cents` and `outstanding_cents`, and moves it `RESOLVED_BY_OFFSET → ATTRIBUTED` when the recomputed `outstanding_cents` becomes strictly greater than 0, bumping its `version` by 1 — a compensating edge out of what is otherwise a terminal status, because offsets are reversible in a way that escheatment and write-off are not. Hop 3 reopens any Medicare obligation in `SATISFIED_BY_OFFSET`, returning it to `OPEN` when the logical clock is at or before `due_at` and to `LATE` when the clock is past `due_at`, clearing `satisfied_at` and `satisfaction_mode` and, in the late case, recomputing `days_late` and `penalty_cents`. The notice itself then recomputes `applied_cents` and `remaining_unapplied_cents`, bumps its `version` by 1, and steps its `state` down — `FULLY_APPLIED → PARTIALLY_APPLIED` when applied cents remain after the reversal, and `PARTIALLY_APPLIED → RECEIVED` when `applied_cents` returns to exactly 0. Offset lines can be listed and filtered by `take_back_notice_id`, `account_id`, `credit_balance_id`, `posted_transaction_id` and `state`.

A payer that disagrees with its own notice may dispute it. Within the 45-day window — that is, while the logical clock is at or before the notice's `dispute_deadline_at` — a `PayerLiaison` acting for that same payer files a dispute with a `dispute_reason`, moving the notice from `RECEIVED` or `PARTIALLY_APPLIED` to `DISPUTED` and bumping its `version` by 1. Once past the deadline the filing is refused with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 409). While a notice is `DISPUTED` no further offset applications may be created against it. The same liaison may withdraw the dispute, taking the notice back to `RECEIVED` when its `applied_cents` is exactly 0 and to `PARTIALLY_APPLIED` when its `applied_cents` is strictly greater than 0, again bumping the `version` by 1 — and offsetting may then resume. A dispute left unresolved does not linger forever: see §3.14. Notices can be listed and filtered by `payer_id` and by `state`.

### 3.11. The Medicare 60-Day Repayment Obligation

Federal law gives a provider sixty days from the day it identifies an overpayment to report and return it. This service models that obligation as its own record, created automatically — never by an explicit call — during attribution, and only when the credit balance's payer is of `payer_type` `MEDICARE` and the computed `payer_portion_cents` is strictly greater than 0. The new obligation carries the `credit_balance_id` of the credit, the `payer_id` of that payer, an `identified_at` copied verbatim from the credit balance's own `identified_at`, a `reportable_amount_cents` frozen at the credit's `payer_portion_cents`, and a `due_at` exactly 60 days after `identified_at`. It opens in `state` `OPEN` with `days_late` and `penalty_cents` at 0 and with `report_reference`, `reported_at`, `satisfied_at` and `satisfaction_mode` all null.

Three derived figures are recomputed on every read of the obligation, during the nightly checkpoint, at self-report time and whenever a cascade reopens the record. `days_elapsed` is the whole floored days from `identified_at` to the logical clock. The obligation is on time exactly when `days_elapsed` is at most 60 — day sixty itself is compliant. `days_late` is `days_elapsed` minus 60 when that difference is positive, and 0 otherwise.

The late assessment is tiered on `days_late` and is always computed against the frozen `reportable_amount_cents`. When `days_late` is 0 the `penalty_cents` is 0. When `days_late` is at least 1 and at most 30, the penalty is two percent of `reportable_amount_cents`, rounded half up to a whole cent. When `days_late` is at least 31 and at most 90, the penalty is five percent, rounded half up. Beyond 90 days late, the penalty is ten percent, rounded half up. The boundaries are pinned: 30 days late is still tier one at two percent, and 31 days late is tier two at five percent; 90 days late is still tier two, and 91 days late is tier three at ten percent.

The `OPEN → LATE` transition is time-driven and belongs to the nightly checkpoint: an obligation still in `OPEN` whose `due_at` is strictly before the logical clock is flipped to `LATE`, with `days_elapsed`, `days_late` and `penalty_cents` recomputed at that moment. Nothing else moves an obligation into `LATE` from `OPEN`.

Self-reporting is the `ComplianceOfficer`'s act. The officer supplies a `report_reference` — the reference string the Medicare contractor issued — and the service stamps `reported_at` from the logical clock and stores that reference. The destination depends on lateness at the moment of the report, evaluated exactly as above. A report filed while the obligation is on time lands `OPEN → REPORTED` and leaves `penalty_cents` at 0. A report filed on an obligation that is `LATE` lands `LATE → REPORTED_LATE` and writes `penalty_cents` from the tiered assessment. So an obligation reported on day sixty is `REPORTED` with no penalty, while the same obligation reported on day sixty-one is `REPORTED_LATE` with one day late and a two-percent penalty. An obligation that has already been reported, or that has already been satisfied in any manner, cannot be reported again and is refused with `ERR_OBLIGATION_INVALID_STATE`.

Reporting is not repaying, and an obligation is only satisfied when the money actually moves. Three routes exist, and each writes a different `satisfaction_mode`. A refund check that reaches the payee settles the obligation as hop 4 of the issue cascade: `OPEN` or `REPORTED` becomes `SATISFIED` and `LATE` or `REPORTED_LATE` becomes `SATISFIED_LATE`, in each case with `satisfied_at` stamped and `satisfaction_mode` set to `REFUND_CHECK`. An offset settles it as hop 4 of the offset cascade: `OPEN`, `LATE` or `REPORTED` becomes `SATISFIED_BY_OFFSET` with `satisfaction_mode` set to `OFFSET`. And a de-minimis write-off settles an already-reported obligation: `REPORTED` becomes `SATISFIED` and `REPORTED_LATE` becomes `SATISFIED_LATE`, with `satisfaction_mode` set to `WRITE_OFF`.

Satisfaction is not permanent. Voiding the check that settled the obligation reopens it, as described in §3.9: `SATISFIED` returns to `OPEN` when the logical clock is at or before `due_at` and to `LATE` when the clock is past it, and `SATISFIED_LATE` returns to `LATE`. Reversing the offset that settled it likewise returns `SATISFIED_BY_OFFSET` to `OPEN` or `LATE` on the same clock-versus-`due_at` test. In every reopening, `satisfied_at` and `satisfaction_mode` are cleared and the derived day counts and penalty are recomputed against the current clock — so an obligation that was satisfied on time, reopened three months later and satisfied again will carry a penalty the second time around. Obligations can be listed and filtered by `credit_balance_id`, by `payer_id` and by `state`.

### 3.12. Unclaimed Property: Dormancy, Due Diligence and Escheatment

When a refund check goes stale, the hospital is holding money that belongs to somebody who never collected it, and unclaimed-property law takes over. A `ComplianceOfficer` opens a record against a `check_disbursement_id`, which must name a check in `state` `STALE` — anything else is `ERR_CHECK_INVALID_STATE` — and at most one record may exist per check, a second attempt being refused with `ERR_ESCHEATMENT_ALREADY_EXISTS`. The officer may supply a `basis` of `ISSUE_DATE` or `LAST_CONTACT`; when omitted it defaults to `ISSUE_DATE`. The record opens in `state` `DORMANT` with `remitted_amount_cents` at 0, `contact_method` null, `due_diligence_sent_at` null and `claimed_at` null.

Creating the record computes the whole dormancy clock. The record's `state_code` is copied from the check's `payee_state_code`, and that jurisdiction fixes `dormancy_days`: California and Texas each impose 1,095 days — three years — while New York and Florida each impose 1,825 days — five years. The `dormancy_start_at` then depends on the chosen basis, and this is the one place in the system where the same check can produce two materially different escheat dates.

- Under the `ISSUE_DATE` basis — the statutory default — `dormancy_start_at` is simply the check's `issued_at`. Account activity after the check was cut is ignored entirely, so this basis always produces the earliest possible escheat date.
- Under the `LAST_CONTACT` basis — used by jurisdictions that reset dormancy whenever the owner is heard from — take the patient account behind the credit balance that the check's refund request was drawn against, find the latest `posted_at` across that account's transactions that have not been reversed, and set `dormancy_start_at` to the later of that instant and the check's `issued_at`. Any non-reversed posting after the issue date therefore pushes the start forward and produces a strictly later escheat date for the very same check.

From there both bases compute the same way: `escheat_due_at` is `dormancy_start_at` plus `dormancy_days` days, and `due_diligence_open_at` is `escheat_due_at` minus 120 days. That 120-day lead is the earliest instant at which the statutory owner-contact letter may be sent.

Recording the owner-contact letter moves the record `DORMANT → DUE_DILIGENCE_SENT`. The officer supplies a `contact_method` of `FIRST_CLASS_MAIL`, `CERTIFIED_MAIL` or `EMAIL`, which is stored alongside a `due_diligence_sent_at` stamped from the logical clock. Two guards apply: the record must be `DORMANT`, or the attempt fails with `ERR_ESCHEATMENT_INVALID_STATE`; and the logical clock must be at or after `due_diligence_open_at`, or the attempt fails with `ERR_DUE_DILIGENCE_TOO_EARLY` (HTTP 409). A letter sent too early is worthless to the state, which is why the lead window is enforced rather than merely recommended.

Remittance is the terminal act. The record must not already be `CLAIMED`, `REMITTED` or `EXEMPT` — those are refused with `ERR_ESCHEATMENT_INVALID_STATE`. It must have `due_diligence_sent_at` set, which is to say it must be in `DUE_DILIGENCE_SENT`; a record still sitting in `DORMANT` passes the state check but is caught here with `ERR_DUE_DILIGENCE_REQUIRED` (HTTP 409). And the dormancy period must actually have elapsed: the logical clock must be at or after `escheat_due_at`, or the attempt fails with `ERR_DORMANCY_NOT_ELAPSED` (HTTP 409). Because due diligence outranks dormancy in the global ordering of §2.8, a `DORMANT` record whose dormancy has also not elapsed reports the missing-due-diligence error rather than the dormancy error.

When remittance succeeds, the record moves `DUE_DILIGENCE_SENT → REMITTED` and its `remitted_amount_cents` is set to the check's `net_check_amount_cents`. Two cascade hops follow. Hop 1 moves the check `STALE → ESCHEATED`, which is terminal for it. Hop 2 moves the owning credit balance `REFUNDED → ESCHEATED`, bumps its `version` by 1 and posts an `ESCHEAT_REMITTANCE` ledger row of positive `net_check_amount_cents` on the account, so the ledger records that the hospital parted with the funds a second time — once to the payee who never cashed the check, and once to the state. `ESCHEATED` is terminal for the credit balance.

Two other exits close the record without any money reaching the state. If the check is voided while the record is still `DORMANT`, the record moves `DORMANT → EXEMPT` and the funds return to the credit balance instead of escheating. If the check is reissued to a payee who resurfaced while the record was already `DUE_DILIGENCE_SENT`, the record moves `DUE_DILIGENCE_SENT → CLAIMED` with `claimed_at` stamped and `remitted_amount_cents` left at 0. `REMITTED`, `CLAIMED` and `EXEMPT` are all terminal. Records can be listed and filtered by `check_disbursement_id` and by `state`.

### 3.13. Audit Reporting of Credit Balance Liability

A `ComplianceOfficer` generates period reports by naming a `report_type` of `CREDIT_BALANCE_LIABILITY`, `MEDICARE_CBR` or `ESCHEAT_HOLDER_REPORT`, a `scope_code` that is either the literal `ALL`, one of the payer type values, or a state code, and three instants: a `period_start_at` and `period_end_at` bounding the closed reporting period, and an `as_of_at` valuation instant. Ordering is enforced — `period_start_at` must be strictly before `period_end_at`, and `period_end_at` must be at or before `as_of_at`; a violation of either is `ERR_INVALID_PERIOD` (HTTP 422) — as is the seven-day separation rule of §2.10, whose violation is `ERR_REPORT_PERIOD_CONFLICT`. The report is created in `state` `DRAFT` and stamped with the generating officer's `X-User-ID` as `generated_by_user_id`.

Generation computes every total at once, and it values the population at `as_of_at` rather than at the logical clock. A credit balance is included when its `identified_at` is at or before `as_of_at` — that bound is inclusive — its `status` is one of the four open-liability statuses `IDENTIFIED`, `UNDER_REVIEW`, `ATTRIBUTED` and `REFUND_PENDING`, and the scope matches: either `scope_code` is `ALL`, or the `payer_type` of the credit balance's payer equals `scope_code`. Included rows are ordered by `identified_at` ascending, breaking ties by `created_at` ascending.

From that population, `line_count` is the number of included rows; `total_liability_cents` is the sum of their `credit_amount_cents`; `patient_liability_cents` is the sum of their `patient_portion_cents`; and `payer_liability_cents` is the sum of their `payer_portion_cents`. The `over_180_count` is the number of included rows whose whole floored days from `identified_at` to `as_of_at` is at least 181 — note the valuation instant, not the logical clock, drives that age. Finally `medicare_at_risk_cents` is the sum of `reportable_amount_cents` over the Medicare repayment obligations whose `state` is `OPEN` or `LATE`, whose `due_at` is at or before `as_of_at`, and whose credit balance is itself in the included population. All of these are pure integer sums with no rounding.

Finalising a report moves it `DRAFT → FINALIZED`, freezing every computed total so the figures can never be regenerated; a report already `FINALIZED` refuses the call with `ERR_REPORT_INVALID_STATE`. `FINALIZED` is terminal. Reports can be listed and filtered by `report_type` and by `state`.

### 3.14. The Nightly Operations Checkpoint and Standing Invariants

Time-driven transitions do not happen spontaneously. They are collected into a single operations checkpoint that a `SystemAdmin` or a `ComplianceOfficer` may run at any point, and which by convention is run nightly. The checkpoint takes no input, mutates whatever the current logical clock now justifies, and reports four counts.

- **Checks go stale.** Every check in `state` `ISSUED` whose `stale_at` is at or before the logical clock moves `ISSUED → STALE`. No ledger movement occurs. The number moved is reported as `staled_check_count`.
- **Obligations go late.** Every Medicare repayment obligation in `state` `OPEN` whose `due_at` is strictly before the logical clock moves `OPEN → LATE`, with `days_elapsed`, `days_late` and `penalty_cents` recomputed. The number moved is reported as `late_obligation_count`.
- **Settled runs close.** Every check run in `state` `ISSUED` in which no check remains in `PENDING` or `ISSUED` moves `ISSUED → CLOSED` and has its `version` bumped by 1 — a run whose checks have all cleared, been voided, gone stale, been reissued or escheated has nothing left to settle. `CLOSED` is terminal for a run and releases its channel window for reuse. The number moved is reported as `closed_batch_count`.
- **Stale disputes are withdrawn.** Every take-back notice in `state` `DISPUTED` whose logical clock reading is strictly past its `dispute_deadline_at` plus 30 days moves `DISPUTED → WITHDRAWN`, and every offset application on that notice still in `APPLIED` is reversed, each running the full offset compensation chain of §3.10 — ledger reversal, credit balance recompute and possible return to `ATTRIBUTED`, and Medicare obligation reopening. `WITHDRAWN` is terminal for a notice. The number withdrawn is reported as `withdrawn_notice_count`.

The checkpoint also re-ages credit balances, though aging is recomputed on every read regardless and so is never stale in the first place.

Two invariants hold at all times and are the fastest way to check an implementation. First, the credit liability invariant: for any credit balance, `credit_amount_cents` always equals `refunded_cents` plus `offset_cents` plus `outstanding_cents`, and the same equality survives every compensating action because voided checks and reversed offsets leave their respective counted sets. Second, the recoupment invariant: for any take-back notice, `total_recoup_cents` always equals `applied_cents` plus `remaining_unapplied_cents`, and the `admin_fee_share_cents` values across a notice's `APPLIED` lines always sum to exactly its `admin_fee_cents`. Underneath both, the ledger invariant: an account's `balance_cents` is always the plain sum of `amount_cents` over every transaction on it, and every reversal row negates its target exactly, so no compensating action ever leaves a residue.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — a payer, an account, a ledger posting, a root-cause finding, a refund request, an approval decision, a check run, a check line, a take-back notice, a set of offset lines, an unclaimed-property record or a compliance report — return `201 Created`. Operations that modify an existing resource, including every state transition, every freeze or release of a state machine, the identification sweep, the operations checkpoint and the logical-clock reposition, return `200 OK`. All endpoints are mounted at the root of the service; every collection is a flat top-level resource addressed by its own id, and relationships travel in request bodies and query filters rather than in nested URLs. Request and response payloads are not repeated here — reconstruct them from the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/set_current_utc`                                  | Set the server's logical clock to a supplied instant          | `SystemAdmin`                      |
| POST   | `/ops/run-aging-sweep`                                     | Run the nightly operations checkpoint                         | `SystemAdmin`, `ComplianceOfficer` |
| POST   | `/payers`                                                  | Register a payer                                              | `SystemAdmin`                      |
| GET    | `/payers`                                                  | List payers                                                   | Any (all six roles)                |
| GET    | `/payers/{payerId}`                                        | Read one payer                                                | Any (all six roles)                |
| POST   | `/patient-accounts`                                        | Open a patient account                                        | `SystemAdmin`, `CreditAnalyst`     |
| GET    | `/patient-accounts`                                        | List patient accounts                                         | Any (all six roles)                |
| GET    | `/patient-accounts/{accountId}`                            | Read one patient account with recomputed balances             | Any (all six roles)                |
| POST   | `/patient-accounts/{accountId}/status`                     | Move an account between OPEN, CLOSED and BAD_DEBT             | `SystemAdmin`                      |
| POST   | `/patient-accounts/{accountId}/transactions`               | Post a ledger transaction against the account                 | `CreditAnalyst`, `SystemAdmin`     |
| GET    | `/account-transactions`                                    | List ledger transactions                                      | Any (all six roles)                |
| GET    | `/account-transactions/{transactionId}`                    | Read one ledger transaction                                   | Any (all six roles)                |
| POST   | `/account-transactions/{transactionId}/reverse`            | Post a reversal negating an existing transaction              | `CreditAnalyst`                    |
| POST   | `/credit-balances/identify-sweep`                          | Run the credit balance identification sweep                   | `CreditAnalyst`                    |
| GET    | `/credit-balances`                                         | List credit balances                                          | Any (all six roles)                |
| GET    | `/credit-balances/{creditBalanceId}`                       | Read one credit balance with recomputed aging                 | Any (all six roles)                |
| POST   | `/credit-balances/{creditBalanceId}/start-review`          | Take an identified credit balance into review                 | `CreditAnalyst`                    |
| POST   | `/credit-balances/{creditBalanceId}/attribute`             | Determine the patient vs payer split                          | `CreditAnalyst`                    |
| POST   | `/credit-balances/{creditBalanceId}/write-off`             | Write off a de-minimis credit balance                         | `ComplianceOfficer`                |
| POST   | `/root-cause-findings`                                     | File a posting-error root-cause finding                       | `CreditAnalyst`                    |
| GET    | `/root-cause-findings`                                     | List root-cause findings                                      | Any (all six roles)                |
| GET    | `/root-cause-findings/{findingId}`                         | Read one root-cause finding                                   | Any (all six roles)                |
| POST   | `/refund-requests`                                         | Prepare a refund request against an attributed credit balance | `CreditAnalyst`                    |
| GET    | `/refund-requests`                                         | List refund requests                                          | Any (all six roles)                |
| GET    | `/refund-requests/{refundRequestId}`                       | Read one refund request                                       | Any (all six roles)                |
| POST   | `/refund-requests/{refundRequestId}/submit`                | Submit a draft or returned refund request for approval        | `CreditAnalyst`                    |
| POST   | `/refund-requests/{refundRequestId}/decision`              | Approve, reject or return a submitted refund request          | `RefundApprover`                   |
| POST   | `/refund-requests/{refundRequestId}/cancel`                | Withdraw a refund request that has not been paid              | `CreditAnalyst`                    |
| GET    | `/refund-approvals`                                        | List approval decisions                                       | Any (all six roles)                |
| GET    | `/refund-approvals/{approvalId}`                           | Read one approval decision                                    | Any (all six roles)                |
| POST   | `/refund-batches`                                          | Open a check run on a disbursement channel                    | `DisbursementOfficer`              |
| GET    | `/refund-batches`                                          | List check runs                                               | Any (all six roles)                |
| GET    | `/refund-batches/{batchId}`                                | Read one check run with recomputed totals                     | Any (all six roles)                |
| POST   | `/refund-batches/{batchId}/items`                          | Add an approved refund request to an open check run           | `DisbursementOfficer`              |
| POST   | `/refund-batches/{batchId}/lock`                           | Freeze a check run's line set ahead of issue                  | `DisbursementOfficer`              |
| POST   | `/refund-batches/{batchId}/unlock`                         | Reopen a locked check run                                     | `DisbursementOfficer`              |
| POST   | `/refund-batches/{batchId}/issue`                          | Cut checks for every pending line in a locked run             | `DisbursementOfficer`              |
| GET    | `/check-disbursements`                                     | List check lines                                              | Any (all six roles)                |
| GET    | `/check-disbursements/{checkId}`                           | Read one check line                                           | Any (all six roles)                |
| POST   | `/check-disbursements/{checkId}/clear`                     | Record that an issued check cleared the bank                  | `DisbursementOfficer`              |
| POST   | `/check-disbursements/{checkId}/void`                      | Void an issued or stale check                                 | `DisbursementOfficer`              |
| POST   | `/check-disbursements/{checkId}/reissue`                   | Cut a replacement line for a stale or voided check            | `DisbursementOfficer`              |
| POST   | `/take-back-notices`                                       | Record a payer take-back / recoupment notice                  | `PayerLiaison`                     |
| GET    | `/take-back-notices`                                       | List take-back notices                                        | Any (all six roles)                |
| GET    | `/take-back-notices/{noticeId}`                            | Read one take-back notice with recomputed applied totals      | Any (all six roles)                |
| POST   | `/take-back-notices/{noticeId}/offset-applications`        | Apply a notice against credit balances via the waterfall      | `CreditAnalyst`                    |
| POST   | `/take-back-notices/{noticeId}/dispute`                    | Payer-side dispute of a take-back notice                      | `PayerLiaison`                     |
| POST   | `/take-back-notices/{noticeId}/withdraw-dispute`           | Payer withdraws its dispute                                   | `PayerLiaison`                     |
| GET    | `/offset-applications`                                     | List offset lines                                             | Any (all six roles)                |
| GET    | `/offset-applications/{offsetApplicationId}`               | Read one offset line                                          | Any (all six roles)                |
| POST   | `/offset-applications/{offsetApplicationId}/reverse`       | Reverse one applied offset line                               | `CreditAnalyst`                    |
| GET    | `/medicare-obligations`                                    | List Medicare 60-day repayment obligations                    | Any (all six roles)                |
| GET    | `/medicare-obligations/{obligationId}`                     | Read one obligation with recomputed lateness and penalty      | Any (all six roles)                |
| POST   | `/medicare-obligations/{obligationId}/report`              | Self-report the overpayment to the Medicare contractor        | `ComplianceOfficer`                |
| POST   | `/escheatment-records`                                     | Open an unclaimed-property record against a stale check       | `ComplianceOfficer`                |
| GET    | `/escheatment-records`                                     | List unclaimed-property records                               | Any (all six roles)                |
| GET    | `/escheatment-records/{escheatmentRecordId}`               | Read one unclaimed-property record                            | Any (all six roles)                |
| POST   | `/escheatment-records/{escheatmentRecordId}/due-diligence` | Record the statutory owner-contact letter                     | `ComplianceOfficer`                |
| POST   | `/escheatment-records/{escheatmentRecordId}/remit`         | Remit the unclaimed funds to the state                        | `ComplianceOfficer`                |
| POST   | `/compliance-reports`                                      | Generate a liability, Medicare CBR or escheat holder report   | `ComplianceOfficer`                |
| GET    | `/compliance-reports`                                      | List compliance reports                                       | Any (all six roles)                |
| GET    | `/compliance-reports/{reportId}`                           | Read one compliance report                                    | Any (all six roles)                |
| POST   | `/compliance-reports/{reportId}/finalize`                  | Freeze a draft report                                         | `ComplianceOfficer`                |

## 5. Error Code Catalogue

Every rejection carries the error envelope of §2.2 with one of the identifiers below in `error_id`. Trigger conditions are not repeated here — each condition is stated in the §2 or §3 narrative that owns the rule it guards, and the global order in which competing conditions are evaluated is fixed by §2.8.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED`               | 401 Unauthorized         |
| `ERR_FORBIDDEN_ROLE`                | 403 Forbidden            |
| `ERR_PAYER_SCOPE_VIOLATION`         | 403 Forbidden            |
| `ERR_APPROVAL_TIER_INSUFFICIENT`    | 403 Forbidden            |
| `ERR_PAYER_NOT_FOUND`               | 404 Not Found            |
| `ERR_ACCOUNT_NOT_FOUND`             | 404 Not Found            |
| `ERR_TRANSACTION_NOT_FOUND`         | 404 Not Found            |
| `ERR_CREDIT_BALANCE_NOT_FOUND`      | 404 Not Found            |
| `ERR_ROOT_CAUSE_FINDING_NOT_FOUND`  | 404 Not Found            |
| `ERR_REFUND_REQUEST_NOT_FOUND`      | 404 Not Found            |
| `ERR_REFUND_APPROVAL_NOT_FOUND`     | 404 Not Found            |
| `ERR_REFUND_BATCH_NOT_FOUND`        | 404 Not Found            |
| `ERR_CHECK_NOT_FOUND`               | 404 Not Found            |
| `ERR_TAKE_BACK_NOTICE_NOT_FOUND`    | 404 Not Found            |
| `ERR_OFFSET_APPLICATION_NOT_FOUND`  | 404 Not Found            |
| `ERR_MEDICARE_OBLIGATION_NOT_FOUND` | 404 Not Found            |
| `ERR_ESCHEATMENT_RECORD_NOT_FOUND`  | 404 Not Found            |
| `ERR_COMPLIANCE_REPORT_NOT_FOUND`   | 404 Not Found            |
| `ERR_INVALID_REQUEST`               | 400 Bad Request          |
| `ERR_INVALID_PAGINATION`            | 400 Bad Request          |
| `ERR_CREDIT_BALANCE_INVALID_STATE`  | 409 Conflict             |
| `ERR_REFUND_REQUEST_INVALID_STATE`  | 409 Conflict             |
| `ERR_BATCH_INVALID_STATE`           | 409 Conflict             |
| `ERR_CHECK_INVALID_STATE`           | 409 Conflict             |
| `ERR_NOTICE_INVALID_STATE`          | 409 Conflict             |
| `ERR_OBLIGATION_INVALID_STATE`      | 409 Conflict             |
| `ERR_ESCHEATMENT_INVALID_STATE`     | 409 Conflict             |
| `ERR_REPORT_INVALID_STATE`          | 409 Conflict             |
| `ERR_TRANSACTION_ALREADY_REVERSED`  | 409 Conflict             |
| `ERR_STALE_VERSION`                 | 412 Precondition Failed  |
| `ERR_SEGREGATION_OF_DUTIES`         | 409 Conflict             |
| `ERR_DUPLICATE_APPROVER`            | 409 Conflict             |
| `ERR_MEDICARE_OBLIGATION_OPEN`      | 409 Conflict             |
| `ERR_DUE_DILIGENCE_REQUIRED`        | 409 Conflict             |
| `ERR_DUE_DILIGENCE_TOO_EARLY`       | 409 Conflict             |
| `ERR_DORMANCY_NOT_ELAPSED`          | 409 Conflict             |
| `ERR_DISPUTE_WINDOW_CLOSED`         | 409 Conflict             |
| `ERR_INVALID_PERIOD`                | 422 Unprocessable Entity |
| `ERR_INVALID_BATCH_WINDOW`          | 422 Unprocessable Entity |
| `ERR_BATCH_WINDOW_OVERLAP`          | 409 Conflict             |
| `ERR_REPORT_PERIOD_CONFLICT`        | 409 Conflict             |
| `ERR_DUPLICATE_PAYER_CODE`          | 409 Conflict             |
| `ERR_DUPLICATE_ACCOUNT_NUMBER`      | 409 Conflict             |
| `ERR_DUPLICATE_BATCH_NUMBER`        | 409 Conflict             |
| `ERR_DUPLICATE_NOTICE_NUMBER`       | 409 Conflict             |
| `ERR_ESCHEATMENT_ALREADY_EXISTS`    | 409 Conflict             |
| `ERR_ACCOUNT_NOT_REFUNDABLE`        | 409 Conflict             |
| `ERR_PAYEE_TYPE_MISMATCH`           | 422 Unprocessable Entity |
| `ERR_TAKE_BACK_NOT_PERMITTED`       | 422 Unprocessable Entity |
| `ERR_TRANSACTION_PAYER_REQUIRED`    | 422 Unprocessable Entity |
| `ERR_REFUND_BELOW_MINIMUM`          | 422 Unprocessable Entity |
| `ERR_CREDIT_ALREADY_CONSUMED`       | 409 Conflict             |
| `ERR_REFUND_EXCEEDS_CREDIT`         | 422 Unprocessable Entity |
| `ERR_NET_BELOW_MIN_CHECK`           | 422 Unprocessable Entity |
| `ERR_BATCH_EMPTY`                   | 409 Conflict             |
| `ERR_NO_ELIGIBLE_CREDIT`            | 422 Unprocessable Entity |
| `ERR_WRITE_OFF_LIMIT_EXCEEDED`      | 422 Unprocessable Entity |
| `ERR_MAX_REVISIONS_EXCEEDED`        | 409 Conflict             |
| `ERR_ACCOUNT_HAS_OPEN_CREDIT`       | 409 Conflict             |
