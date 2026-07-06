# Public Notice Legal Ads API — Product Requirements Document

## 1. Introduction

Local governments, courts, law firms, and lenders are all bound by statute to publish certain notices — foreclosure sales, probate hearings, and public bid solicitations — in a qualified newspaper of record for a legally prescribed number of consecutive weeks. Today this work is fragmented across email, phone calls, spreadsheets, and paper affidavits, which makes it far too easy to miss a statutory deadline, run a notice in a paper that does not legally qualify, or lose the sworn affidavit of publication that a court later demands as proof. This platform replaces that patchwork with a single system of record that carries a legal notice from first draft through proofing, weekly publication scheduling, publisher fulfilment, sworn affidavit, invoicing, payment, and finally a permanently searchable digital archive.

The system serves four distinct constituencies. Advertisers (law firms, government agencies, and individuals) draft and submit notices, approve typeset proofs, schedule the weekly run, and settle invoices. Publishers (newspaper staff) record which insertions actually ran, report missed runs, and swear the affidavit of publication. Compliance officers police statutory correctness — voiding defective affidavits and archiving completed notices. A platform administrator provisions the reference data (newspapers, accounts, statutory rules) and drives the logical clock used for test-driving. Because the downstream consequence of an error is a legally void publication, the platform is built around precise cost estimation, hard statutory gating, optimistic-concurrency-safe rescheduling, and an auditable billing ledger.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the principal's role. If either header is missing, or `X-User-Role` is not one of the four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are spelled exactly `Advertiser`, `Publisher`, `ComplianceOfficer`, and `PlatformAdmin`.

Two roles are entity-backed. When `X-User-Role` is `Advertiser`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's owning account to `X-User-ID` — an advertiser may act only on notices, proofs, insertions, invoices, and payments whose `account_id` chain resolves to its own account. When `X-User-Role` is `Publisher`, `X-User-ID` is the `id` of the acting `Newspaper`; ownership checks compare the target resource's `newspaper_id` to `X-User-ID`, so a publisher may publish or skip an insertion, or issue an affidavit, only for its own newspaper.

The other two roles are opaque operators. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is not compared to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a supplied value outside that band is clamped or rejected as an out-of-range value. `offset` defaults to 0 and has a minimum of 0. Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. Every list response echoes `limit` and `offset` in `meta` alongside `total_count` (the total number of matching records ignoring pagination) and `has_more` (true when unread records remain beyond the current window).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix. Most resources also carry three common audit fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 and increases by exactly one on every mutation that changes the resource. `created_at` is fixed at creation and never changes; `updated_at` is refreshed on every mutation.

Two resource kinds are deliberately lighter: an `InvoiceLineItem` and a `Payment` are immutable ledger records that carry only `id` and `created_at` — they have no `updated_at` and no `version`, because they are never modified after creation. Every other resource (`Newspaper`, `Account`, `StatutoryRequirement`, `Notice`, `Insertion`, `Proof`, `Affidavit`, `Invoice`) carries the full `created_at`, `updated_at`, and `version` set.

Whenever a mutation cascades into a related resource — for example, a publisher publishing an insertion that in turn advances its parent notice — each individual resource that actually changes has its own `version` incremented and its own `updated_at` refreshed. A resource that is merely read as part of the operation, but not changed, is left untouched.

### 2.5. Optimistic Concurrency Control on Rescheduling

Scheduling and rescheduling a notice's weekly run is guarded by optimistic concurrency control. The schedule endpoint (`POST /notices/{id}/schedule`) requires a non-optional `expected_notice_version` field carrying the client's last observed `version` of the target notice. The server compares `expected_notice_version` against the notice's current `version`; if they do not match — because another writer has already superseded the schedule and advanced the notice's `version` since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Two strictly sequential reschedules, where the second still quotes the pre-advance version, reproduce this rejection deterministically and prevent the second caller from silently overwriting a schedule it never observed. No other endpoint takes a version field; only the schedule operation is version-checked.

### 2.6. Money, Counts, and the Pricing Basis

All monetary amounts are expressed as an integer number of cents. Because every rate and every count in this system is an integer, cost arithmetic produces integer cents directly and no fractional rounding is ever applied to money. Line counting, however, does round: the typeset `line_count` of a body of copy is the length of the text in characters divided by the newspaper's `chars_per_line`, rounded up to the next whole line. This ceiling is always applied per insertion on that insertion's own text — the system never sums characters across multiple insertions and takes a single ceiling.

Each newspaper charges on one of two bases, given by its `pricing_basis`: `PER_LINE` or `PER_WORD`. Under `PER_LINE`, the first insertion of a run (the one whose `sequence_number` is 1) is charged at `line_rate_first_cents` per line, and every later insertion (any `sequence_number` of 2 or more) is charged at `line_rate_subsequent_cents` per line. Under `PER_WORD`, every insertion regardless of `sequence_number` is charged at `word_rate_cents` per word, applied to the notice's `word_count`. A notice's `word_count` is the number of whitespace-separated tokens in its `body_text`.

### 2.7. The Logical Clock

The platform runs on a logical clock rather than wall-clock time, so that statutory deadlines, publication dates, and affidavit timestamps are fully test-drivable. On startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it holds this default and never falls back to real wall-clock time. A platform administrator may advance the clock by supplying a new instant in the `to_iso8601` field. The logical clock is the reference for recording an insertion's `published_date`, stamping an affidavit's `issued_at`, and evaluating statutory publication cutoffs.

### 2.8. Nested Resource Retrieval and Path Resolution

Several resources are reachable through nested paths (for example, the proofs, insertions, or affidavits belonging to a notice) or through reverse-reachability list queries filtered by a foreign key. Path parameters are validated left to right: for a nested path, the parent `id` segment must resolve to a live resource before the child segment is considered. Any path `id` or foreign-key body field that does not resolve to a live resource yields `ERR_NOT_FOUND` (HTTP 404). A malformed request body — a missing required field, a value of the wrong type, or an invalid enum value — yields `ERR_VALIDATION` (HTTP 400).

### 2.9. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned `error_id` is deterministic. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); second, authorization including ownership (`ERR_UNAUTHORIZED`); third, existence of every referenced resource, resolved left-to-right (`ERR_NOT_FOUND`); fourth, that the target resource is in a state permitting the requested transition (`ERR_INVALID_STATE`, HTTP 409); and only then the domain-specific business checks described throughout §3. Body well-formedness (`ERR_VALIDATION`) is a precondition of interpreting the request at all. The business checks themselves are further ordered within the workflows that use them, described where each workflow is specified.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Reference Data

Before any notice can be placed, a `PlatformAdmin` seeds three kinds of reference data. Registering a newspaper of record captures its legal `name`, the `county` (an UPPER_SNAKE jurisdiction code) it serves, and whether it qualifies as a newspaper of general circulation via `circulation_qualified` (which defaults to true). The registration also fixes the paper's commercial terms — its `pricing_basis`, `chars_per_line`, `line_rate_first_cents`, `line_rate_subsequent_cents`, `word_rate_cents`, and the flat `affidavit_fee_cents` charged for the sworn affidavit of publication. Two operational limits complete the record: `publication_weekday`, the single weekday on which the paper prints (following the convention where Monday is 0 and Sunday is 6), and `edition_line_capacity`, the maximum total legal-notice lines a single edition can carry across all notices. The paper may also declare `blackout_dates`, a list of half-open date ranges (defaulting to an empty list) during which it does not print.

Creating an advertiser account captures its `name`, its `account_type` — one of `LAW_FIRM`, `GOVERNMENT`, or `INDIVIDUAL` — and its `credit_limit_cents`, the maximum committed exposure the account may carry (defaulting to 0). An account also carries a `status` of `ACTIVE` or `SUSPENDED`, defaulting to `ACTIVE`; only an `ACTIVE` account may submit notices. The two balance fields, `outstanding_balance_cents` and `committed_balance_cents`, are computed on read and are described in §3.7.

A statutory requirement encodes the publication law for one class of notice in one jurisdiction. It names the `notice_type` it governs — one of `FORECLOSURE`, `PROBATE`, or `BID` — the `county` it applies to, the `min_insertions` (the minimum number of consecutive weekly insertions the law demands), and `min_days_before_deadline` (the number of days by which the last insertion must precede the notice's statutory anchor date). The pair of `notice_type` and `county` is unique; the platform holds at most one rule per class per jurisdiction.

### 3.2. Drafting and Submitting a Notice

An `Advertiser` opens a legal notice by drafting it. The draft names the owning `account_id`, the target `newspaper_id`, the `notice_type`, the `county` of publication, a short `title`, the full legal `body_text`, and the `deadline_date` — the statutory anchor (hearing, sale, or bid-open date) the run must precede. A freshly drafted notice enters `DRAFT` status.

At creation the server derives several fields from the copy and the governing law. It computes `word_count` from the `body_text` and `line_count` by ceiling the character length of `body_text` against the target newspaper's `chars_per_line`. It looks up the statutory requirement matching the notice's `notice_type` and `county`; if none exists, the draft is refused with `ERR_STATUTORY_REQUIREMENT_MISSING` (HTTP 422). When a rule is found, its `min_insertions` is copied onto the notice as `required_insertions`. The server then computes `estimated_cost_cents`, a provisional charge that projects exactly `required_insertions` runs of the submitted copy: each projected insertion uses the notice's `line_count`, and the per-insertion charge follows the newspaper's pricing basis (§2.6) — under `PER_LINE`, the first projected insertion is priced with `line_rate_first_cents` and every remaining projected insertion with `line_rate_subsequent_cents`, each multiplied by `line_count`; under `PER_WORD`, every projected insertion is priced as `word_count` multiplied by `word_rate_cents`. The projected per-insertion charges are summed to yield `estimated_cost_cents`. A newly created notice has `insertions_published` and `paid_insertion_count` at 0, a `final_cost_cents` that is null until the run completes, and a `compliance_status` of `PENDING`.

Submitting a `DRAFT` notice advances it to `SUBMITTED` and is where the fiscal gate is enforced. The notice must currently be in `DRAFT`. The owning account must be `ACTIVE`; a submit attempted against a `SUSPENDED` account is rejected with `ERR_ACCOUNT_SUSPENDED` (HTTP 409). The account must also have room under its credit limit: the account's current `committed_balance_cents` plus the notice's `estimated_cost_cents` must be at most the account's `credit_limit_cents`, and if that sum would exceed the limit the submit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). When submission succeeds, the system snapshots the copy for review by creating a `Proof` in `PENDING` status whose `proof_text` is a frozen copy of the notice's `body_text` at that moment.

### 3.3. Proofing the Copy

Every submitted notice has exactly one live `Proof` awaiting the advertiser's review, and the proof drives the notice's progress out of `SUBMITTED`. The `Advertiser` reviews the frozen `proof_text` and either approves or rejects it, optionally attaching a `reviewer_note` in either case.

Approving the proof requires it to be `PENDING` and to belong to this notice — its `notice_id` must reference the notice under review. Approval moves the proof from `PENDING` to `APPROVED` and, as a cascade, advances the parent notice from `SUBMITTED` to `PROOF_APPROVED`, clearing the copy for scheduling.

Rejecting the proof likewise requires it to be `PENDING`. Rejection moves the proof from `PENDING` to `REJECTED` and, as a cascade, returns the parent notice from `SUBMITTED` back to `DRAFT`. This is the revision cycle: once back in `DRAFT`, the advertiser may edit the `body_text` and submit again, at which point a fresh `Proof` is minted against the revised copy. A proof that is not `PENDING` cannot be approved or rejected again; such an attempt is an invalid state transition (`ERR_INVALID_STATE`, HTTP 409).

### 3.4. Scheduling and Adjusting the Weekly Run

Once a notice is `PROOF_APPROVED`, the `Advertiser` schedules its consecutive-weekly run, transitioning the notice from `PROOF_APPROVED` to `SCHEDULED`. The request supplies the `first_publication_date` — the date of the first insertion — together with the `expected_notice_version` described in §2.5. From the first date the system generates exactly `required_insertions` insertion dates, one per week: the first insertion runs on `first_publication_date`, and each subsequent insertion runs 7 days after the previous one. Each generated `Insertion` is created in `SCHEDULED` status with a `sequence_number` counting from 1 for the first date upward, and with its `newspaper_id` copied from the parent notice for edition-capacity aggregation. A successful schedule increments the notice's `version` by one.

Several statutory and operational gates guard scheduling, evaluated after the standard authentication, authorization, existence, and state checks. First, the target newspaper must legally qualify: its `circulation_qualified` must be true and the notice's `county` must equal the newspaper's `county`; a failure of either yields `ERR_NEWSPAPER_NOT_QUALIFIED` (HTTP 422). Next, a statutory requirement must still match the notice's `notice_type` and `county`, failing which the request is refused with `ERR_STATUTORY_REQUIREMENT_MISSING` (HTTP 422). Then every generated date is checked against the newspaper's calendar: each date must fall on the newspaper's `publication_weekday`, or the request is rejected with `ERR_INVALID_PUBLICATION_DAY` (HTTP 422); no date may fall inside a blackout range, where a date is blacked out when it is on or after a range's start and strictly before that range's end, or the request is rejected with `ERR_BLACKOUT_DATE` (HTTP 422); and the last of the generated dates must fall on or before the notice's `deadline_date` minus the statutory `min_days_before_deadline` days, or the request is rejected with `ERR_INSERTION_AFTER_DEADLINE` (HTTP 422). Finally, edition capacity is enforced per date: for each generated date, the sum of the `line_count` of the insertions already occupying that newspaper-and-date edition (those in `SCHEDULED` or `PUBLISHED` status) plus this notice's own `line_count` must be at most the newspaper's `edition_line_capacity`, or the request is rejected with `ERR_EDITION_CAPACITY_EXCEEDED` (HTTP 409).

A notice already in `SCHEDULED` may be rescheduled — the same operation applied again supersedes the prior schedule. Rescheduling is permitted only while no insertion of the notice has yet published, that is, while `insertions_published` is 0; it also demands a matching `expected_notice_version` and re-runs the identical weekday, blackout, deadline, and edition-capacity checks. On success, every existing `SCHEDULED` insertion of the notice is set to `CANCELLED`, a fresh set of `SCHEDULED` insertions is minted, and the notice's `version` is incremented by one. Because each reschedule advances the `version`, a second sequential reschedule that still quotes the pre-advance `expected_notice_version` is rejected under optimistic concurrency control with `ERR_STALE_VERSION` (HTTP 412), as described in §2.5.

Between scheduling and the first publication, the advertiser may fine-tune the run in two ways. A single extra insertion may be added to a `SCHEDULED` notice by supplying its `scheduled_date`; the new insertion takes a `sequence_number` of one more than the highest existing sequence number on the notice, and extra runs are advertiser-elected and do not change the notice's `required_insertions` coverage. A manually added date must satisfy the same weekday, blackout, and deadline temporal checks, and it must also respect consecutive-week adjacency: the added date must be exactly 7 days away from the nearest existing active (`SCHEDULED` or `PUBLISHED`) insertion of the same notice. A larger gap, or a same-day collision with an existing insertion, breaks adjacency and is rejected with `ERR_INSERTION_SPACING_VIOLATION` (HTTP 409); the added date is separately subject to the edition-capacity rule, which on breach yields `ERR_EDITION_CAPACITY_EXCEEDED` (HTTP 409). The advertiser may also cancel a still-`SCHEDULED` insertion, moving it from `SCHEDULED` to `CANCELLED`; cancellation is allowed only while the parent notice is itself `SCHEDULED`, and because a `SCHEDULED` insertion was never counted, no counters change.

### 3.5. Fulfilment: Publishing, Skipping, and Make-Goods

As each print date arrives, the `Publisher` records the outcome of that insertion. Recording a run advances the insertion from `SCHEDULED` to `PUBLISHED`. This is permitted only when the insertion is `SCHEDULED`, its parent notice is in `SCHEDULED` or `RUNNING` status, and the logical clock has reached or passed the insertion's `scheduled_date` — a publish attempted before that date is rejected with `ERR_PUBLISH_BEFORE_SCHEDULED` (HTTP 422). Only the publisher that owns the insertion's `newspaper_id` may record the run; another publisher is refused for lack of ownership.

The publisher reports the `line_count_actual` — the true typeset line count the paper produced, which may differ from the notice's original `line_count` after reformatting. On publication the system stamps `published_date` with the current clock instant and books the insertion's `cost_cents`. For an ordinary (non-make-good) insertion, the booked cost follows the newspaper's basis: under `PER_LINE` it is `line_count_actual` multiplied by the rate for this insertion's position — `line_rate_first_cents` when the `sequence_number` is 1, otherwise `line_rate_subsequent_cents`; under `PER_WORD` it is the notice's `word_count` multiplied by `word_rate_cents`. A make-good insertion is always free: its `cost_cents` is 0 regardless of basis. Publishing also increments the notice's `insertions_published` by one, and — only when the insertion is not a make-good — increments `paid_insertion_count` by one; make-goods never increment the billable count.

When a scheduled run is missed, the publisher records a skip, moving the insertion from `SCHEDULED` to `SKIPPED`. A skip is allowed only on an insertion whose `is_make_good` is false; attempting to skip a make-good insertion (which would chain one make-good into another) is rejected with `ERR_MAKE_GOOD_NOT_SKIPPABLE` (HTTP 409). Skipping automatically creates a replacement: a new `Insertion` with `is_make_good` set to true, its `makes_good_insertion_id` pointing back to the skipped insertion's `id`, the same `sequence_number` as the insertion it replaces, a `cost_cents` of 0, a status of `SCHEDULED`, and a `scheduled_date` exactly 7 days after the skipped insertion's date. The skip then recomputes the notice's `compliance_status`.

Publishing an insertion bubbles state up to the parent notice according to how many insertions have now published against the requirement. While at least one but fewer than `required_insertions` insertions have published, the notice sits in `RUNNING`, and each such publication recomputes its `compliance_status`. Once the published count reaches the requirement, the run completes, as described next.

### 3.6. Completion, Compliance, and Cost Finalization

A notice's run completes the moment `insertions_published` reaches `required_insertions`. For a multi-insertion run this is the transition from `RUNNING` to `PUBLISHED`; for a single-insertion run — a `BID` notice whose requirement is one insertion, for instance — the notice moves directly from `SCHEDULED` to `PUBLISHED` on the first and only publication. Both paths perform the identical set of completion side effects.

At completion the system finalizes the actual charge into `final_cost_cents`. Unlike the estimate, the final charge bills only what actually ran: it considers exactly the insertions in `PUBLISHED` status that are not make-goods, taken in ascending `sequence_number` order. Each such insertion contributes, under `PER_LINE`, its own `line_count_actual` multiplied by the rate for its own `sequence_number` (`line_rate_first_cents` when that number is 1, otherwise `line_rate_subsequent_cents`), and under `PER_WORD`, the notice's `word_count` multiplied by `word_rate_cents`. These per-insertion charges are summed to give `final_cost_cents`. Because it uses each insertion's reported `line_count_actual` and excludes skipped, cancelled, and make-good insertions, the final charge diverges from `estimated_cost_cents` whenever the paper reformats copy or a run is skipped and made good for free.

Completion also recomputes `compliance_status`. Compliance is `PENDING` while `insertions_published` is below `required_insertions`. Once the requirement is met, the system takes the latest `published_date` among all the notice's `PUBLISHED` insertions — make-goods included — and compares it to the statutory cutoff, which is the notice's `deadline_date` minus `min_days_before_deadline` days. If that latest published date is on or before the cutoff, the notice is `COMPLIANT`; if it falls even one day past the cutoff, it is `NON_COMPLIANT`. This same recomputation runs whenever an insertion of the notice publishes, skips, or is otherwise changed, so a make-good that lands past the cutoff can flip a notice out of compliance.

Completion assembles the bill. The system creates an `Affidavit` in `PENDING` status for the notice, and a `DRAFT` `Invoice` whose `account_id` and `notice_id` are copied from the notice. The invoice's `subtotal_cents` equals the notice's `final_cost_cents`, and is itemized into one `InvoiceLineItem` per `PUBLISHED` non-make-good insertion. Each such line records the charged `insertion_id`, a human-readable `description` (for example, "Insertion 1 of 2"), the insertion's `line_count` (its `line_count_actual`), the `rate_cents` applied, and the extended `amount_cents` for that line — and the line amounts sum to the subtotal. The affidavit fee is then resolved by a tiered waiver: the invoice's `affidavit_fee_cents` is 0 when `subtotal_cents` is at least the waiver threshold of 3,000 cents, and otherwise equals the newspaper's flat `affidavit_fee_cents`. When the fee is not waived, it is itemized as an additional line with a null `insertion_id`, a `description` of "Affidavit of publication fee", a `line_count` of 0, a `rate_cents` equal to the fee, and an `amount_cents` equal to the fee. The invoice's `total_cents` is `subtotal_cents` plus its `affidavit_fee_cents`. Finally, because a fresh `DRAFT` invoice now exists, the account's `committed_balance_cents` is recomputed.

### 3.7. Affidavit of Publication, Billing, and Payments

With the run complete and its bill drafted, the `Publisher` swears the affidavit of publication. Issuing the affidavit moves it from `PENDING` to `ISSUED` and requires the affidavit to be `PENDING`, the parent notice to be in `PUBLISHED` status, and the acting publisher to own the notice's `newspaper_id`. The publisher supplies the `sworn_by` name of the representative attesting the affidavit. On issue, the system freezes `publication_dates` to the ascending list of the `published_date` values of the notice's `PUBLISHED` insertions and stamps `issued_at` with the current clock. Issuance cascades: the notice advances from `PUBLISHED` to `AFFIDAVIT_ISSUED`, the notice's `DRAFT` invoice advances to `ISSUED`, and — because an issued invoice is now money owed — the account's `outstanding_balance_cents` is recomputed, rising by the invoice's `total_cents`.

A `ComplianceOfficer` may void a defective affidavit, moving it from `ISSUED` to `VOID`, optionally recording a `reason`. Voiding is refused if the notice's invoice has already been paid: when that invoice is in `PAID` status the void is rejected with `ERR_INVOICE_PAID_LOCK` (HTTP 409), because a settled bill cannot be unwound. Otherwise the void is a compensating reversal: the notice reverts from `AFFIDAVIT_ISSUED` back to `PUBLISHED` (re-arming it for a corrected affidavit), the notice's `ISSUED` invoice moves to `VOID`, and the account's `outstanding_balance_cents` is recomputed, falling by that invoice's `total_cents`.

An `Advertiser` settles an issued invoice by recording a payment against it. The payment names the target `invoice_id` and an `amount_cents`; the resulting `Payment` record also carries the `account_id` copied from the invoice. The amount must be strictly greater than 0 and at most the invoice's remaining balance — its `total_cents` minus the already-paid `amount_paid_cents`; an amount that is 0 or negative, or that exceeds the remaining balance, is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422). Each accepted payment increases the invoice's `amount_paid_cents`, and when the accumulated `amount_paid_cents` reaches or exceeds the invoice's `total_cents`, the invoice advances from `ISSUED` to `PAID`. Every payment recomputes the account's `outstanding_balance_cents`, lowering it by the payment amount.

The two account balances are computed views over the account's invoices and payments, refreshed on every invoice status change and on every payment, and returned when an account is fetched. The `outstanding_balance_cents` is the settled view: it is the sum of `total_cents` across the account's `ISSUED` invoices, minus the sum of `amount_cents` across all the account's payments. Invoices in `VOID` and `PAID` status contribute nothing to the outstanding figure — a paid invoice's total is already netted out by its payments. The `committed_balance_cents` is the exposure view used by the credit-limit gate at submit time: it is the `outstanding_balance_cents` plus the sum of `total_cents` across the account's `DRAFT` invoices, so that a notice which has published but not yet been affidavited still consumes credit.

### 3.8. The Digital Archive

Once a notice has an issued affidavit, a `ComplianceOfficer` archives it, moving it from `AFFIDAVIT_ISSUED` to the terminal `ARCHIVED` state. Archival requires the notice to be in `AFFIDAVIT_ISSUED` status and its linked affidavit to be `ISSUED`. An archived notice becomes read-only but remains fully query-visible: it is the permanent, searchable public record of the publication.

The archive is browsable through a filtered notice search ordered by `created_at` ascending, narrowing results by owning `account_id`, `newspaper_id`, `notice_type`, `county`, lifecycle `status`, and `compliance_status`. Related child records are reached by reverse-reachability queries: a notice's proofs, insertions, and affidavits are each listable by the notice; insertions are also filterable across the platform by `notice_id`, `newspaper_id`, `scheduled_date`, `status`, and the self-referential `makes_good_insertion_id` that links a make-good to the insertion it replaced. Invoices are listable by `account_id`, `notice_id`, and `status`; invoice line items by `invoice_id` and `insertion_id`; and payments by `account_id` and `invoice_id`. Statutory requirements are listable by `notice_type` and `county`.

## 4. Endpoint Definitions

The table below summarizes every endpoint. Creating a brand-new resource returns HTTP 201; operations that modify or transition an existing resource, and all reads, return HTTP 200. Request and response payloads are not repeated here — the fields each operation accepts and the side effects it produces are specified in the §3 workflows above.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | PlatformAdmin |
| POST | `/newspapers` | Register a newspaper of record | PlatformAdmin |
| GET | `/newspapers/{id}` | Fetch a newspaper | PlatformAdmin, Advertiser, Publisher, ComplianceOfficer |
| POST | `/accounts` | Create an advertiser account | PlatformAdmin |
| GET | `/accounts/{id}` | Fetch an account with computed balances | PlatformAdmin, Advertiser |
| POST | `/statutory-requirements` | Define the statutory rule for a (notice_type, county) | PlatformAdmin |
| GET | `/statutory-requirements` | List statutory requirements | PlatformAdmin, Advertiser, ComplianceOfficer |
| POST | `/notices` | Create a DRAFT notice | Advertiser |
| GET | `/notices/{id}` | Fetch a notice with computed fields | PlatformAdmin, Advertiser, Publisher, ComplianceOfficer |
| GET | `/notices` | Search the digital archive of notices | PlatformAdmin, Advertiser, Publisher, ComplianceOfficer |
| POST | `/notices/{id}/submit` | Submit a draft notice for proofing | Advertiser |
| GET | `/notices/{id}/proofs` | List a notice's proofs | PlatformAdmin, Advertiser, ComplianceOfficer |
| POST | `/proofs/{id}/approve` | Approve a pending proof | Advertiser |
| POST | `/proofs/{id}/reject` | Reject a pending proof | Advertiser |
| POST | `/notices/{id}/schedule` | Generate or supersede the weekly insertion run | Advertiser |
| GET | `/notices/{id}/insertions` | List a notice's insertions | PlatformAdmin, Advertiser, Publisher, ComplianceOfficer |
| POST | `/notices/{id}/insertions` | Add one extra insertion to a scheduled notice | Advertiser |
| GET | `/insertions/{id}` | Fetch one insertion | PlatformAdmin, Advertiser, Publisher, ComplianceOfficer |
| GET | `/insertions` | List insertions with filters | PlatformAdmin, Advertiser, Publisher, ComplianceOfficer |
| POST | `/insertions/{id}/publish` | Record that an insertion ran | Publisher |
| POST | `/insertions/{id}/skip` | Record a missed run and create a make-good | Publisher |
| POST | `/insertions/{id}/cancel` | Cancel a still-scheduled insertion | Advertiser |
| GET | `/notices/{id}/affidavits` | List a notice's affidavits | PlatformAdmin, Advertiser, Publisher, ComplianceOfficer |
| GET | `/affidavits/{id}` | Fetch one affidavit | PlatformAdmin, Advertiser, Publisher, ComplianceOfficer |
| POST | `/affidavits/{id}/issue` | Swear and issue the affidavit of publication | Publisher |
| POST | `/affidavits/{id}/void` | Void an issued affidavit | ComplianceOfficer |
| GET | `/invoices/{id}` | Fetch one invoice | PlatformAdmin, Advertiser |
| GET | `/invoices` | List invoices with filters | PlatformAdmin, Advertiser |
| GET | `/invoice-line-items/{id}` | Fetch one invoice line item | PlatformAdmin, Advertiser |
| GET | `/invoice-line-items` | List invoice line items with filters | PlatformAdmin, Advertiser |
| POST | `/payments` | Record a payment against an issued invoice | Advertiser |
| GET | `/payments/{id}` | Fetch one payment | PlatformAdmin, Advertiser |
| GET | `/payments` | List payments with filters | PlatformAdmin, Advertiser |
| POST | `/notices/{id}/archive` | Archive an affidavited notice | ComplianceOfficer |

## 5. Error Code Catalogue

The trigger conditions for each error are given in the §2 and §3 narratives where the relevant rule is specified.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VALIDATION` | 400 |
| `ERR_NEWSPAPER_NOT_QUALIFIED` | 422 |
| `ERR_STATUTORY_REQUIREMENT_MISSING` | 422 |
| `ERR_INVALID_PUBLICATION_DAY` | 422 |
| `ERR_BLACKOUT_DATE` | 422 |
| `ERR_INSERTION_AFTER_DEADLINE` | 422 |
| `ERR_PUBLISH_BEFORE_SCHEDULED` | 422 |
| `ERR_INSERTION_SPACING_VIOLATION` | 409 |
| `ERR_EDITION_CAPACITY_EXCEEDED` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_ACCOUNT_SUSPENDED` | 409 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_INVOICE_PAID_LOCK` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_MAKE_GOOD_NOT_SKIPPABLE` | 409 |











