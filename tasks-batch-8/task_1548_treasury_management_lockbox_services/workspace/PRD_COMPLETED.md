# Treasury Lockbox Services API — Product Requirements Document

## 1. Introduction

Commercial treasury clients do not open their own remittance mail. They redirect incoming customer checks to bank-operated lockbox sites, and the bank does the work: receiving couriered batches, capturing each check, balancing the captured tallies against the courier manifest, transmitting remittance data back to the client in an agreed file format, granting funds availability according to published schedules, and billing for it all once a month through account analysis — where service charges are offset by an earnings credit on collected balances. When the bank misses its service levels, the client is owed error credits. This document specifies the API that runs that entire operation.

The surface area is deliberately wide. Bank operations staff provision banks, manage bank posture, and drive the logical business clock. Implementation specialists onboard customers and draft service agreements, which a separate activator then brings live under segregation of duties. Lockbox sites carry daily cutoffs, availability schedules keyed to payer routing prefixes, and transmission formats with explicit supersession. Day to day, site operators capture remittance batches item by item, dispose of each item (accept, return, or raise an exception), and balance and close the batch; customers decide their own exception items within a bounded window before the system decides for them. An image archive supports retrieval requests under a seven-year retention rule with a one-hour service level. A business-day checkpoint auto-decides stale exceptions, expires stale image requests, settles acknowledged batches, and accrues collected balances; a month-end checkpoint finalizes analysis cycles, computes earnings credits and service charges, applies SLA credits, and settles statements net of approved error credits. All resources are mounted under the `/banks` prefix, and every date-sensitive rule in this document evaluates against the bank's logical business date rather than any wall clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` identifying the actor, and `X-User-Role` naming the actor's role. A request with either header missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Eight roles exist, spelled exactly as follows:

- `BankOperationsAdmin` — bank-level operator; owns bank lifecycle and posture, the business-day rollover, and the logical clock.
- `TreasuryImplementer` — bank-side implementation specialist; onboards customers, drafts agreements, builds sites and availability schedules, drafts transmission formats.
- `TreasuryActivator` — bank-side activator; activates, suspends, resumes, and terminates agreements, customers, sites, and formats. Must be a different individual than the implementer on the same artifact.
- `LockboxOperator` — bank-side site operator; runs daily capture, balancing, transmission, and image fulfillment.
- `CustomerOperator` — customer-side operator; acknowledges transmissions, decides and escalates exceptions, requests images, files error credit requests, and reports SLA incidents.
- `BillingSpecialist` — bank-side billing runner; closes analysis cycles, settles statements, triages SLA incidents.
- `BillingApprover` — bank-side billing approver; reviews error credit requests, and must differ from the BillingSpecialist who worked the cycle.
- `Auditor` — read-only oversight.

When `X-User-Role` is `CustomerOperator`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a customer compare the resource's `customer_id` field to `X-User-ID`, and that role's reads are scoped to its own customer. For that role, a request that names a specific resource owned by a different customer — whether a nested path carrying another customer's id, a flat single-resource read, or a write the role is otherwise authorized to perform — is rejected with `ERR_NOT_FOUND` (HTTP 404), exactly as if the resource did not exist; the flat and bank-scoped list endpoints instead omit resources outside the actor's own customer from their results. AvailabilitySchedules carry no `customer_id` of their own, so for a `CustomerOperator` the flat and bank-scoped availability-schedule lists come back empty, while flat single-schedule reads are not ownership-scoped and may be read by any role. For every other role — `BankOperationsAdmin`, `TreasuryImplementer`, `TreasuryActivator`, `LockboxOperator`, `BillingSpecialist`, `BillingApprover`, and `Auditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `implemented_by_user_id`, `activated_by_user_id`, `decided_by_user_id`, or `reviewed_by_user_id`) but never compares it to any entity's `id`.

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

Requests to unknown paths, and methods not supported by a path, are likewise rejected with `ERR_NOT_FOUND` (HTTP 404) in this envelope.

### 2.3. Pagination

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and must be non-negative; a non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Results are always sorted by `created_at` ascending, with ties broken in the order the server persisted the resources. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

List endpoints additionally accept optional equality filters drawn from the resource's own fields and foreign keys. Depending on the resource these include `status`, `tier`, `format_kind`, `capture_status`, `transmission_status`, `batch_status`, `business_date`, `availability_tier`, `reason_code`, `request_reason`, `incident_kind`, `line_kind`, and the relationship selectors `bank_id`, `customer_id`, `agreement_id`, `site_id`, `batch_id`, `item_id`, `cycle_id`, `supersedes_format_id`, `reference_batch_id`, and `reference_request_id`.

### 2.4. Resource Identity, Timestamps, and Optimistic Concurrency

Every resource in this system carries four common properties: `id`, a server-minted UUID with no type prefix; `created_at` and `updated_at`, ISO 8601 UTC timestamps with three fractional digits; and `version`, an integer starting at 1 on creation that increments by one on every mutation of the resource, with `updated_at` refreshed at the same moment.

Three writes are guarded by optimistic concurrency control. Agreement activation and transmission-format activation each require the request to carry `expected_agreement_version` holding the client's last-observed `version` of the parent ServiceAgreement; analysis-cycle settlement requires `expected_cycle_version` holding the client's last-observed `version` of the AnalysisCycle. If the parent's version has advanced since the client last read it — another writer has legitimately moved the resource forward, for example by activating the agreement or by a confirmation cascade bumping a cycle — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), so the client never overwrites state it has not observed. No endpoint other than these three accepts a version field.

### 2.5. Bank Posture and the Logical Business Clock

Each bank runs under a `posture` of `OPERATING`, `SUSPENDED`, or `LIQUIDATING`. `SUSPENDED` blocks value-extending operations across the bank; `LIQUIDATING` blocks everything. Any mutating call that requires an operating bank and finds otherwise is rejected with `ERR_BANK_NOT_OPERATING` (HTTP 409); bank-level administration itself is exempt from this gate — bank-level administration covers bank provisioning and posture transitions (suspend, resume, liquidate), the logical-clock set, the business-day close, and the analysis-cycle close, and reads are never posture-gated. Every other mutating endpoint requires the bank `OPERATING`.

Time in this system is logical. The server's logical clock starts at 2026-08-01T00:00:00Z and never falls back to the wall clock; a BankOperationsAdmin-only capability sets it to an arbitrary UTC instant supplied as `to_iso8601`, which is how cutoff, retention, and SLA windows are driven deterministically. Every bank carries `current_business_date`, defaulting to 2026-08-01 at bank creation and advancing only through the business-day close, and `current_analysis_cycle_index`, a monotonic count of closed monthly analysis cycles starting at 0.

### 2.6. Nested Resource Addressing and Bank Scoping

Resource URLs mirror the ownership hierarchy: a Bank owns Customers; a Customer owns ServiceAgreements; a ServiceAgreement owns LockboxSites and TransmissionFormats; a LockboxSite owns RemittanceBatches and AvailabilitySchedules; a RemittanceBatch owns RemittanceItems. Every resource records its lineage through foreign keys — `bank_id`, `customer_id`, `agreement_id`, `site_id`, `batch_id`, and `item_id` appear on the resources that sit below those parents, with bank references denormalized onto lower levels to support cross-cutting lookups. Path identifiers are validated left to right: each id in a nested path must exist and must belong to the enclosing parent within the same bank, and the first failure is rejected with `ERR_NOT_FOUND` (HTTP 404). References supplied in request bodies — an image request's `item_id`, an error credit's `cycle_id`, an incident's `reference_batch_id` or `reference_request_id`, a format's `supersedes_format_id` — must likewise resolve to an entity inside the same bank and customer scope, or the request fails with `ERR_INVALID_REFERENCE` (HTTP 409); this guard covers exception raising, image-request creation, incident reporting, and error-credit filing. Flat single-resource reads and flat filtered lists are also provided for every resource type (see §4) so that a resource can be reached directly by its `id`.

### 2.7. Monetary Precision, Rounding, and Basis Points

All monetary amounts are integer cents; rates are expressed in basis points per annum, so a bank-wide earnings credit rate of 175 means 1.75 percent. Wherever a computation produces a fractional cent or a fractional basis point, the result is rounded half-up — half a cent rounds away from zero. Statement line items are each rounded half-up to whole cents first, and only then summed; the system never sums unrounded amounts and rounds once at the end. The earnings credit uses an actual-over-360 day-count convention against a 10,000 basis-point denominator. SLA error rates are expressed in whole basis points, rounded half-up. Availability and exception deadlines use business-day arithmetic; there are no fractional days.

### 2.8. Segregation of Duties

Four hand-offs must be performed by two different individuals, enforced by comparing `X-User-ID` values recorded at each step: the TreasuryActivator who activates a ServiceAgreement must differ from the `implemented_by_user_id` who implemented it; the LockboxOperator who closes a batch must differ from the operator who began its capture; the CustomerOperator who decides an exception must differ from the operator who raised it; and the BillingApprover who approves an error credit must differ from the BillingSpecialist who finalized or settled the cycle. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

### 2.9. Validation Order and Request Rejection

Incoming requests are checked against the following rules in the order listed — a request that fails an earlier check is rejected immediately and never reaches a later one:

1. Authentication context: both headers present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. Role authorization for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`, 403).
3. Path existence, validated left to right within the bank (`ERR_NOT_FOUND`, 404).
4. Bank posture permits the operation — `SUSPENDED` blocks value-extending operations, `LIQUIDATING` blocks everything (`ERR_BANK_NOT_OPERATING`, 409).
5. Where the operation requires a `LIVE` site, the site check fires first (`ERR_SITE_NOT_LIVE`, 409); then the target resource must be in a lifecycle state from which the requested transition is defined (`ERR_INVALID_STATE_TRANSITION`, 409 — item dispositions on a non-`CAPTURED` item report `ERR_ITEM_NOT_IN_CAPTURED_STATE`, and a decide on an already-resolved exception reports `ERR_EXCEPTION_ALREADY_DECIDED`, both at this step).
6. Segregation of duties on the four guarded hand-offs (`ERR_SEGREGATION_OF_DUTIES`, 409).
7. Optimistic concurrency: the expected-version field matches the parent's current `version` (`ERR_STALE_VERSION`, 412).
8. Referential integrity of body-supplied references within the bank (`ERR_INVALID_REFERENCE`, 409).
9. Batch balance invariant — captured tallies equal the courier manifest (`ERR_BATCH_OUT_OF_BALANCE`, 409).
10. Site go-live prerequisites — an active availability schedule and an active transmission format (`ERR_SITE_LACKS_AVAILABILITY_SCHEDULE` / `ERR_SITE_LACKS_TRANSMISSION_FORMAT`, 409).
11. Image retention window (`ERR_IMAGE_RETENTION_EXPIRED`, 409).
12. Exception decision window — once the auto-decision moment has passed, a customer decision is refused (`ERR_AUTO_DECISION_IMMUTABLE`, 409).
13. Customer is `ACTIVE` (or `ONBOARDING` for the first agreement) for value-extending operations (`ERR_CUSTOMER_NOT_ACTIVE`, 409).
14. Termination and decommission blockers — unsettled cycles, open batches (`ERR_CUSTOMER_NOT_SETTLED` / `ERR_SITE_HAS_OPEN_BATCHES`, 409).
15. Uniqueness within the bank: `routing_number`, `tax_id`, `agreement_number`, `site_code`, and the per-site-per-date `batch_reference` (`ERR_DUPLICATE_UNIQUE_FIELD`, 409).

Independently of this business ordering, a request body that is malformed — a missing required field, an unrecognized enum value, or an out-of-range numeric — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Bank Provisioning, Posture, and the Business-Day Checkpoint

A `BankOperationsAdmin` creates a bank with its `legal_name`, a nine-digit ABA `routing_number` that is unique across banks (a duplicate is refused with `ERR_DUPLICATE_UNIQUE_FIELD`), the bank-wide `default_earnings_credit_rate_bp` in basis points per annum (a non-negative integer), and optionally `sla_credit_breach_threshold_bp` (likewise non-negative), which defaults to 200 — a month's service is in breach once its confirmed error rate reaches two hundred basis points of handled items. A new bank begins with `posture` `OPERATING`, a `current_business_date` of 2026-08-01, and `current_analysis_cycle_index` at zero.

Suspending the bank moves `OPERATING → SUSPENDED` and cascades immediately: every `LIVE` LockboxSite drops to `SUSPENDED`, every RemittanceBatch still in `CAPTURING` or `BALANCED` becomes `HELD` through compound-status recompute, and no new batches or image retrieval requests are accepted anywhere in the bank while the suspension holds. Resuming moves `SUSPENDED → OPERATING`, but only while no `CONFIRMED` SLA incident has been left unresolved for more than thirty days — an incident counts as unresolved while it still sits in `CONFIRMED`, and its age is measured from its `occurred_on_business_date` to the bank's `current_business_date`; the sites that the suspension cascade took down return to `LIVE`, provided no other suspension cause still holds them. Liquidation moves `OPERATING → LIQUIDATING`, is terminal, and is permitted only once every customer is `TERMINATED` and every AnalysisCycle that has left `OPEN` is `SETTLED` — an in-flight `OPEN` cycle never blocks liquidation.

The business-day close is the bank's daily checkpoint, run by a `BankOperationsAdmin`. It advances `current_business_date` by one business day and then, in the course of the close: every ExceptionItem whose auto-decision moment has arrived while still `PENDING` or `ESCALATED` is auto-decided; every ImageRetrievalRequest still `REQUESTED` more than thirty calendar days after filing expires to `EXPIRED` and raises a `LATE_IMAGE_FULFILLMENT` incident; every RemittanceBatch sitting `READY_TO_SETTLE` with an `ACKED` transmission settles, posting its ledger credit; every `READY_TO_SETTLE` batch whose items all came back as returns is rejected (a batch carrying no items at all is never rejected by this rule); and for every `ACTIVE` customer the close grows `collected_balance_accumulator_cents` by the day's cleared amount — the accepted totals of batches settling that day, counting only amounts whose `availability_date` has been reached, since funds that have not yet cleared are not collected — increments `days_in_cycle_elapsed` by one, and refreshes the customer's running `average_collected_balance_cents` for the in-flight cycle.

### 3.2. Customer Onboarding and Agreement Implementation

A `TreasuryImplementer` creates a Customer with `legal_name`, a `tax_id` (the customer's EIN, unique within the bank, with duplicates refused as `ERR_DUPLICATE_UNIQUE_FIELD`), and the `deposit_account_number` used for credits and charges. The customer starts as a `PROSPECT` with `collected_balance_accumulator_cents` and `days_in_cycle_elapsed` at zero. Beginning onboarding moves `PROSPECT → ONBOARDING`; the customer then becomes `ACTIVE` automatically the moment its first ServiceAgreement reaches `ACTIVE`, with no separate activation call.

Agreement drafting captures the commercial terms: `agreement_number` (unique within the bank), the fee schedule — `monthly_maintenance_fee_cents` charged regardless of volume, `per_item_capture_fee_cents` per accepted item, `per_exception_decision_fee_cents` per exception decision rendered, and `per_image_retrieval_fee_cents` per fulfilled image retrieval, all four non-negative integers — and an optional `earnings_credit_rate_bp` override (also non-negative). The override is honored at calculation time only when `ecr_override_allowed` is true; that flag defaults to false, and a disallowed override is silently ignored when the earnings credit is computed. A new agreement is a `DRAFT`.

Implementation moves `DRAFT → IMPLEMENTED`: the customer must be `ONBOARDING` or `ACTIVE` (otherwise `ERR_CUSTOMER_NOT_ACTIVE`), the bank must be `OPERATING`, and the step stamps `implemented_by_user_id` with the implementer's `X-User-ID`. Activation moves `IMPLEMENTED → ACTIVE` and is deliberately somebody else's job — the activator's `X-User-ID` must differ from `implemented_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), the customer must still be `ONBOARDING` or `ACTIVE`, and the request must carry `expected_agreement_version` matching the agreement's current `version` (`ERR_STALE_VERSION`, HTTP 412). Activation stamps `activated_by_user_id`, increments the agreement's `version` by one, and — when the customer was still `ONBOARDING` — flips the customer to `ACTIVE`.

Suspension and resumption cascade in both directions of the tree. Suspending a customer (`ACTIVE → SUSPENDED`) takes its `ACTIVE` agreements to `SUSPENDED`, its `LIVE` sites to `SUSPENDED`, and every one of its batches whose capture has not yet closed (`capture_status` `RECEIVED`, `CAPTURING`, `BALANCED`, or `OUT_OF_BALANCE`) to `HELD`; resuming (`SUSPENDED → ACTIVE`) requires the bank to be `OPERATING` (`ERR_BANK_NOT_OPERATING` otherwise), restores the agreements and sites that the customer-suspension cascade itself took down — an agreement or site suspended directly stays suspended, and a site carrying several suspension causes returns to `LIVE` only once every cause has lifted — and releases the customer's held batches. An agreement can also be suspended and resumed on its own — suspension cascades to its child sites, resumption requires the customer `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE` otherwise) and the bank `OPERATING`, and brings the sites the cascade took down back to `LIVE`. Terminating an agreement, from either `ACTIVE` or `SUSPENDED`, requires every one of its LockboxSites `DECOMMISSIONED` (a surviving site blocks with `ERR_INVALID_STATE_TRANSITION`) and every AnalysisCycle referencing it `SETTLED` (`ERR_CUSTOMER_NOT_SETTLED` otherwise). Terminating a customer requires all agreements `TERMINATED` (a surviving agreement blocks with `ERR_INVALID_STATE_TRANSITION`), every AnalysisCycle that has left `OPEN` to be `SETTLED` — an in-flight `OPEN` cycle never blocks termination (otherwise `ERR_CUSTOMER_NOT_SETTLED`), and no ImageRetrievalRequest still `REQUESTED`.

One fiscal gate cuts across everything in this and the next sections: value-extending operations — implementing an agreement, creating a remittance batch, filing an image request — require the customer to be `ACTIVE`, or `ONBOARDING` when the customer's first agreement is the object, and are otherwise refused with `ERR_CUSTOMER_NOT_ACTIVE`.

### 3.3. Lockbox Sites, Availability Schedules, and Transmission Formats

Each site is created under an agreement with a `site_code` unique within the bank (for example LBX-CHI-01), the `postal_box_address` remittances are mailed to, a `daily_cutoff_time_local` in HH:MM twenty-four-hour form, and an IANA `timezone` such as America/Chicago. The cutoff and the timezone together decide which business day a delivered batch books to. A new site starts in `PROVISIONING`.

Going live moves `PROVISIONING → LIVE` and gates on three things: the parent agreement must be `ACTIVE`; the site must have at least one `ACTIVE` AvailabilitySchedule (`ERR_SITE_LACKS_AVAILABILITY_SCHEDULE`); and the agreement must have at least one `ACTIVE` TransmissionFormat (`ERR_SITE_LACKS_TRANSMISSION_FORMAT`). A site that was suspended re-enters `LIVE` through the same operation, which then requires only that the parent agreement is still `ACTIVE`, the customer `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE` otherwise), and the bank `OPERATING` — the schedule and format prerequisites are not re-checked, since a previously live site satisfied them once. Either path clears all of the site's recorded suspension causes and releases the site's held batches. Suspending a site — directly or through any parent cascade — moves `LIVE → SUSPENDED`, and a suspended site refuses new remittance batches with `ERR_SITE_NOT_LIVE`. Decommissioning runs from either `LIVE` or `SUSPENDED` to `DECOMMISSIONED`: both paths require that no batch on the site still sits in `RECEIVED`, `CAPTURING`, `BALANCED`, or `OUT_OF_BALANCE` (`ERR_SITE_HAS_OPEN_BATCHES`), and the `LIVE` path additionally requires that no image request for items on the site is still `REQUESTED` (`ERR_INVALID_STATE_TRANSITION` otherwise).

Availability schedules are the site's float policy. Each schedule carries a `routing_number_pattern` of one to nine digits matched as a prefix against an item's payer routing number (the pattern 0710, for instance, catches a Federal Reserve district), a `tier` of `SAME_DAY`, `ONE_DAY`, or `TWO_DAY`, an `effective_from` date, an optional `effective_to` (absent means open-ended; a supplied `effective_to` earlier than `effective_from` is `ERR_INVALID_REQUEST`), and a `priority` — when several patterns match, the lowest `priority` value wins, ties break toward the later `effective_from`, and any remaining tie breaks toward the schedule with the earlier `created_at` (and, should even `created_at` tie, toward the schedule the server persisted first). Schedules are born `ACTIVE` and are later retired to `RETIRED` by the implementer.

Transmission formats describe the data file the bank sends the customer: a `format_kind` of `BAI2`, `EDI820`, or `CUSTOM_CSV`, a free-form `version_label`, flags `include_invoice_detail` and `include_images` (both defaulting to false), and an optional `supersedes_format_id` pointing at the `ACTIVE` format this one replaces. A new format is a `DRAFT`. Activating a format requires the agreement `ACTIVE` and `expected_agreement_version` matching the parent agreement's current `version` (`ERR_STALE_VERSION`, HTTP 412), because activation mutates the parent — the agreement's `version` increments by one, and the format named by `supersedes_format_id`, if any, cascades to `SUPERSEDED`. Retiring runs to `RETIRED`: from `ACTIVE` it is allowed only while no batch under the agreement still sits with `transmission_status` `PENDING` (`ERR_INVALID_STATE_TRANSITION` otherwise) — the check is agreement-wide because batches do not record which format they will transmit under; from `SUPERSEDED` it is unconditional.

### 3.4. Remittance Intake: Batches, Capture, Balancing, and Item Disposition

A `LockboxOperator` creates a RemittanceBatch against a `LIVE` site — anything else fails `ERR_SITE_NOT_LIVE` — supplying the courier manifest: `batch_reference` (unique per site per business date, enforced as `ERR_DUPLICATE_UNIQUE_FIELD`), `received_at` (the timestamp the courier delivered the work), `declared_item_count`, and `declared_total_cents` (both non-negative integers). At receipt the system projects the batch's `business_date`: `received_at` is converted into the site's `timezone`, and if the resulting local time of day is strictly before `daily_cutoff_time_local`, the batch books to the bank's `current_business_date`; otherwise it rolls forward one business day. Arrival exactly at the cutoff rolls forward — the same-day window closes on the stroke of `daily_cutoff_time_local`. Every batch is born with `capture_status` `RECEIVED`, `transmission_status` `PENDING`, and compound `batch_status` `OPEN`.

Beginning capture moves `RECEIVED → CAPTURING` and requires the site `LIVE` and the bank `OPERATING`. While capturing, the operator posts items one by one with `check_number`, the payer's nine-digit ABA `payer_routing_number`, `amount_cents` (a positive integer), `payee_name`, and an optional `invoice_reference`; each item lands in `CAPTURED` and the batch's `captured_item_count` and `captured_total_cents` accumulate as items arrive.

From `CAPTURED`, an item has three exits, and attempting any of the three on an item that is no longer `CAPTURED` is rejected with `ERR_ITEM_NOT_IN_CAPTURED_STATE`; only Accept additionally gates on the batch's capture status — Return and Raise exception are permitted whenever the item is `CAPTURED`, regardless of whether the batch sits in `CAPTURING`, `BALANCED`, or `OUT_OF_BALANCE`:

- **Accept** (`CAPTURED → ACCEPTED`) requires the batch in `CAPTURING` or `BALANCED`. Acceptance assigns the item's `availability_tier` and `availability_date`, grows the batch's `accepted_item_count` by one and `accepted_total_cents` by `amount_cents`, and — when the tier is `SAME_DAY` — adds `amount_cents` to the batch's `same_day_credit_cents`.
- **Return** (`CAPTURED → RETURNED`) sends the item back undeposited.
- **Raise exception** (`CAPTURED → ON_EXCEPTION`) flags the item with a `reason_code` of `AMOUNT_MISMATCH`, `PAYEE_MISMATCH`, `MISSING_INVOICE_REF`, `STALE_DATED`, or `DUPLICATE_SUSPECTED`, plus a `default_decision` of `PAY` or `RETURN` that the system will apply if the customer stays silent. Raising creates a `PENDING` ExceptionItem whose `auto_decision_at` sits two business days after the current business date at that day's site cutoff, and pushes the batch from `OPEN` to `DECISIONS_PENDING` if it is not already there.

Availability on the accept path anchors on the batch's `business_date`, which was already cutoff-adjusted at receipt. The eligible schedules are the site's `ACTIVE` AvailabilitySchedules whose `routing_number_pattern` is a prefix of the item's `payer_routing_number`, whose `effective_from` is on or before the anchor date, and whose `effective_to` is either empty or on or after the anchor. If no schedule qualifies, the tier defaults to `TWO_DAY`; otherwise the winner follows the precedence of §3.3 — lowest `priority`, then later `effective_from`, then earliest schedule `created_at`. The item's `availability_date` is the anchor plus zero business days for `SAME_DAY`, one for `ONE_DAY`, or two for `TWO_DAY`. The batch's `same_day_credit_cents` is recomputed on every acceptance rather than cached: while the batch is still being worked it is provisional and reflects only items accepted so far, and it freezes for good when capture closes; the frozen figure remains on the batch as its same-day credit of record — settlement itself accrues collected balances per item by `availability_date` as §3.6 describes, not from this figure.

Balancing is the reconciliation between capture and the courier manifest: `captured_item_count` must equal `declared_item_count` and `captured_total_cents` must equal `declared_total_cents`. When both agree, the batch advances `CAPTURING → BALANCED`. When either differs, the balance attempt moves the batch to `OUT_OF_BALANCE` and the failed invariant is reported as `ERR_BATCH_OUT_OF_BALANCE`. An operator may also force a batch from `CAPTURING` to `OUT_OF_BALANCE` directly, and from `OUT_OF_BALANCE` the operator resumes capture — `OUT_OF_BALANCE → CAPTURING` — to post corrections before balancing again.

Closing moves `BALANCED → CLOSED`. It requires that every item on the batch has reached `ACCEPTED`, `RETURNED`, `DECISIONED_PAY`, or `DECISIONED_RETURN`, and that the closer's `X-User-ID` differs from the operator who began capture (`ERR_SEGREGATION_OF_DUTIES`). As capture closes, the compound status resolves: if any item landed in `RETURNED` or `DECISIONED_RETURN`, the batch's `batch_status` becomes `REJECTED`; otherwise it becomes `READY_TO_SETTLE`.

### 3.5. Exception Decisioning and Image Retrieval

An ExceptionItem is one-to-one with the RemittanceItem it flags and carries the `reason_code` and `default_decision` supplied at raising, the computed `auto_decision_at`, and — empty until a decision is rendered — `decision`, `decided_by_user_id`, and `decided_at`. Its `status` walks `PENDING`, optionally `ESCALATED`, and finally `DECIDED` or `AUTO_DECISIONED`.

The customer decides by submitting a `decision` of `PAY` or `RETURN`. The decide is accepted only while the exception is `PENDING` or `ESCALATED` — anything else is `ERR_EXCEPTION_ALREADY_DECIDED` — only when the decider's `X-User-ID` differs from the operator who raised the exception (`ERR_SEGREGATION_OF_DUTIES`), and only while the bank's current business date has not passed the auto-decision date: once `auto_decision_at` has gone by, the exception belongs to the system and a late customer decision is refused with `ERR_AUTO_DECISION_IMMUTABLE`. A recorded decision stamps `decision`, `decided_at`, and `decided_by_user_id`. Deciding `PAY` moves the item `ON_EXCEPTION → DECISIONED_PAY` and re-anchors availability on the business date of the decision rather than the original batch date — the exception detour can push availability two or more business days later — growing the batch's `accepted_item_count` and `accepted_total_cents`, and its `same_day_credit_cents` when the recomputed tier is `SAME_DAY`. Deciding `RETURN` moves the item to `DECISIONED_RETURN`. Either outcome increments the customer's open-cycle `exception_decision_count` by one, and resolving the last pending exception on a batch whose capture has closed moves the batch `DECISIONS_PENDING → READY_TO_SETTLE`.

Escalation buys time exactly once: a `PENDING` exception moves to `ESCALATED` and its `auto_decision_at` extends by one business day; an `ESCALATED` exception cannot be escalated again (`ERR_INVALID_STATE_TRANSITION`), and from `ESCALATED` both customer decision and system auto-decision behave exactly as they do from `PENDING`. Auto-decision runs inside the business-day close: any exception still `PENDING` or `ESCALATED` on or after its auto-decision date becomes `AUTO_DECISIONED`, taking `decision` from `default_decision`, recording `decided_by_user_id` as the system, setting `decided_at` to `auto_decision_at`, and producing the same downstream item and batch effects as a manual decision.

Image retrieval is the customer-facing side of the archive. A `CustomerOperator` files a request naming the `item_id` (which must resolve to an item of their own within the same bank, else `ERR_INVALID_REFERENCE`), a `request_reason` of `AUDIT`, `DISPUTE_SUPPORT`, `RESEARCH`, or `LEGAL`, and `requested_image_kinds`, a non-empty subset of `CHECK_FRONT`, `CHECK_BACK`, `REMIT_STUB`, and `ENVELOPE`; the customer must be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE`). At creation the request computes `retention_expires_at` — seven calendar years from the item's capture timestamp (a leap-day capture maps to February 28 of the target year) — and `sla_due_at`, exactly one hour after the request is made (a fixed one-hour interval; no business-calendar arithmetic is applied); if the retention window has already lapsed, the request is created directly in `DENIED`. Fulfillment by a `LockboxOperator` moves `REQUESTED → FULFILLED` and is permitted only while the request is still inside retention (`ERR_IMAGE_RETENTION_EXPIRED` afterwards); it sets `fulfilled_at` and a server-minted `fulfillment_uri` (the fulfill request carries no payload fields), increments the open cycle's `image_retrieval_fulfilled_count`, and, when the fulfillment lands after `sla_due_at`, raises a `LATE_IMAGE_FULFILLMENT` incident in `REPORTED`. Denial moves `REQUESTED → DENIED`. A request still `REQUESTED` thirty calendar days after filing expires to `EXPIRED` at the business-day close, raising the same late-fulfillment incident.

### 3.6. Transmission, Acknowledgement, and Settlement Posting

Transmission runs on the batch's second dimension. Transmitting moves `PENDING → TRANSMITTED` — and, as a retry, `TRANSMISSION_FAILED → TRANSMITTED` — but only once capture is `CLOSED` and an `ACTIVE` TransmissionFormat exists for the agreement (`ERR_TRANSMISSION_FORMAT_INACTIVE` otherwise). Transmission records only the status transition — no payload is generated or stored, and no incident is raised automatically on the transmit path; `LATE_TRANSMISSION` incidents are filed manually per §3.8. The customer acknowledges receipt (`TRANSMITTED → ACKED`), and an operator records a failed transmission (`TRANSMITTED → TRANSMISSION_FAILED`).

The batch's compound `batch_status` is derived and never written directly. `OPEN` (or `DECISIONS_PENDING`) moves to `HELD` whenever a bank or customer suspension cascade catches the batch — agreement and site suspensions do not hold batches, though a suspended site still refuses new batches and new captures with `ERR_SITE_NOT_LIVE`. The hold is a single flag: the bank's resume, the customer's resume, or the site's go-live each clear it for every batch in their subtree, whatever originally set it, and a `HELD` compound status is observational only — it does not by itself block item disposition or other batch operations. `OPEN` moves to `DECISIONS_PENDING` the moment any item goes `ON_EXCEPTION`. `DECISIONS_PENDING` moves to `READY_TO_SETTLE` when the last `PENDING` exception is decided or auto-decided and capture is `CLOSED`. Two terminal paths then run inside the business-day close: a `READY_TO_SETTLE` batch whose transmission is `ACKED` becomes `SETTLED` — its `accepted_total_cents` posts as a credit to the customer's deposit account, and the customer's collected-balance accumulator is credited weighted by `availability_date`, so only matured amounts count as collected — while a `READY_TO_SETTLE` batch whose items are all `RETURNED` or `DECISIONED_RETURN` becomes `REJECTED` instead.

### 3.7. Account Analysis: Cycle Close, Statement Composition, and Settlement

Account analysis is the monthly billing pass. A `BillingSpecialist` closes the analysis cycle — for every `ACTIVE` customer at once, or for a single customer when the optional `customer_id` is supplied (a supplied `customer_id` that does not resolve to a customer of the bank fails with `ERR_NOT_FOUND`) — and a customer's `OPEN` cycle moves to `FINALIZED` when its `cycle_end_date` equals the bank's current business date; a close that finds no `OPEN` cycle whose `cycle_end_date` is the current business date finalizes nothing and is not an error. Billing parameters come from the agreement in force: the cycle's `agreement_id` references the `ACTIVE` agreement at close (the earliest-created `ACTIVE` agreement, if several are active). While a cycle is still `OPEN` its `agreement_id` is empty — the reference is established at finalization, not before; if no agreement is `ACTIVE` at the close, the reference falls back to the customer's most recently created agreement that is not `TERMINATED`, and if none exists the cycle finalizes with an empty `agreement_id` and every fee rate treated as zero. The cycle carries `cycle_index`, a per-customer monotonic counter starting at one, and the inclusive bounds `cycle_start_date` and `cycle_end_date`. A customer's first cycle — `cycle_index` one — opens the moment its first ServiceAgreement reaches `ACTIVE`, with `cycle_start_date` booked to the bank's current business date on that day; every cycle spans a calendar month, its `cycle_end_date` the last day of the month containing its `cycle_start_date`, and the fresh `OPEN` cycle that follows a close starts the day after its predecessor's `cycle_end_date`.

Finalization computes, in this order:

- `average_collected_balance_cents` — `collected_balance_accumulator_cents` divided by `days_in_cycle_elapsed`, rounded half-up to whole cents; if the cycle elapsed zero days (possible only when a cycle opens and closes on the same day at termination), the average is zero.
- `gross_service_charges_cents` — the sum of four charges: the flat `monthly_maintenance_fee_cents`; `accepted_item_count` multiplied by `per_item_capture_fee_cents`; `exception_decision_count` multiplied by `per_exception_decision_fee_cents`; and `image_retrieval_fulfilled_count` multiplied by `per_image_retrieval_fee_cents`. Each line is rounded half-up to whole cents first, and only then are the lines summed — never the reverse.
- `earnings_credit_cents` — the rate is the agreement's `earnings_credit_rate_bp` when `ecr_override_allowed` is true and the override is set, and the bank's `default_earnings_credit_rate_bp` otherwise. The raw credit is the average collected balance multiplied by the rate and by the days elapsed, divided by 360 and by the 10,000 basis-point denominator, then rounded half-up to whole cents, floored at zero, and capped at `gross_service_charges_cents` — the bank never pays the customer for excess credit.
- `sla_error_rate_bp`, `sla_breach`, and `sla_credit_cents` — per the service-level arithmetic of §3.8.
- `net_amount_due_cents` — gross charges minus the earnings credit, floored at zero, then reduced by any SLA credit and floored at zero again.

The close also emits the statement's AnalysisLineItems — `MAINTENANCE` with `quantity` one; `PER_ITEM_CAPTURE`, `PER_EXCEPTION_DECISION`, and `PER_IMAGE_RETRIEVAL` with quantities taken from the cycle counters; each line's `unit_price_cents` copied from the agreement at close and its `extended_amount_cents` equal to `quantity` multiplied by `unit_price_cents`; plus a `SLA_CREDIT` line when the cycle is in breach, which carries negative `quantity`, negative `unit_price_cents`, and a negative `extended_amount_cents` so it reduces the statement total. SLA incidents whose `occurred_on_business_date` falls within `cycle_start_date` through `cycle_end_date` inclusive are attached to the cycle — their `cycle_id` is set here — and confirmed incidents attached to a breaching cycle move `CONFIRMED → CREDITED` at finalization. The bank's `current_analysis_cycle_index` increments by one when the close finalized at least one cycle — it does not move on a no-op close — and a fresh `OPEN` cycle opens for each customer. Finalization also zeroes the customer's `collected_balance_accumulator_cents`, `days_in_cycle_elapsed`, and running `average_collected_balance_cents`, so the fresh cycle accrues from scratch. The counters themselves accrue through the cycle: `accepted_item_count` counts items that moved into `ACCEPTED` or `DECISIONED_PAY`, `exception_decision_count` counts exceptions that reached `DECIDED` or `AUTO_DECISIONED`, and `image_retrieval_fulfilled_count` counts requests fulfilled.

Settlement is the BillingSpecialist's debit run. From `FINALIZED`, settlement requires that no `SUBMITTED` ErrorCreditRequest remains against the cycle (`ERR_CYCLE_HAS_OPEN_DISPUTES`) and that `expected_cycle_version` match the cycle's current `version` (`ERR_STALE_VERSION`, HTTP 412); the customer's deposit account is then debited `net_amount_due_cents` and the cycle's `version` increments by one. From `DISPUTED`, settlement additionally requires every ErrorCreditRequest against the cycle resolved to `APPROVED`, `PARTIALLY_APPROVED`, or `DENIED`, and the approved credits apply in a fixed order — earnings credit first, then the SLA credit, then approved error credits — so the debit is gross charges minus the earnings credit minus the SLA credit minus the sum of approved credits, floored at zero. Attempting to settle a cycle in any status other than `FINALIZED` or `DISPUTED` fails with `ERR_CYCLE_NOT_FINALIZED`.

### 3.8. Service-Level Incidents and Error Credits

SLAIncidents track the bank's misses, in four kinds: `LATE_TRANSMISSION`, `LATE_IMAGE_FULFILLMENT`, `MISSED_CUTOFF_POSTING`, and `DATA_FORMAT_ERROR`. A `CustomerOperator` or a `BillingSpecialist` reports one manually with `incident_kind` and `occurred_on_business_date`; `reference_batch_id` is required for `LATE_TRANSMISSION`, `MISSED_CUTOFF_POSTING`, and `DATA_FORMAT_ERROR`, while `reference_request_id` is required for `LATE_IMAGE_FULFILLMENT` — a missing required reference is `ERR_INVALID_REQUEST` (HTTP 400) — and every reference must resolve within the bank (`ERR_INVALID_REFERENCE`). The system also raises incidents on its own — a late image fulfillment and an expired image request — as described in §3.5. An incident is born `REPORTED` with `breach_confirmed` false and `cycle_id` empty until the covering cycle closes. Confirmation or rejection by a `BillingSpecialist` is defined only from `REPORTED` — a second review attempt meets `ERR_SLA_INCIDENT_ALREADY_REVIEWED` — and confirmation sets `breach_confirmed` true; if the attached cycle is already `FINALIZED` or `DISPUTED`, its `sla_error_count`, error rate, breach flag, and `sla_credit_cents` are recomputed, the `SLA_CREDIT` line item is added or removed to match, and `net_amount_due_cents` is recomputed (net of approved error credits when the cycle is `DISPUTED`). Only confirmed incidents feed the cycle's `sla_error_count`.

The cycle's service-level arithmetic works as follows. The error-rate denominator is one, or the sum of `accepted_item_count` and `exception_decision_count`, whichever is larger, so an idle cycle never divides by zero. `sla_error_rate_bp` is `sla_error_count` multiplied by 10,000 and divided by that denominator, rounded half-up to whole basis points. `sla_breach` holds when the rate reaches the bank's `sla_credit_breach_threshold_bp` — a rate exactly at the threshold is a breach, one basis point below it is not. On breach, `sla_credit_cents` is ten percent of `gross_service_charges_cents`, rounded half-up to whole cents; otherwise it is zero. Confirmed incidents left unresolved for more than thirty days also block a bank resume (§3.1).

When the customer disputes a statement, an ErrorCreditRequest is filed against a `FINALIZED` (or already `DISPUTED`) cycle — filing against a cycle in any other status fails with `ERR_INVALID_STATE_TRANSITION` — with the `cycle_id`, the `requested_credit_cents` (a positive integer), and a `reason_code` of `SLA_NOT_APPLIED`, `BILLING_RATE_ERROR`, `DUPLICATE_CHARGE`, or `ECR_MISCALCULATION`; filing against a `FINALIZED` cycle cascades it to `DISPUTED` (an already-`DISPUTED` cycle simply gains another request), and the request starts `SUBMITTED`. A `BillingApprover` then rules; ruling on a request no longer `SUBMITTED` fails with `ERR_INVALID_STATE_TRANSITION`. Full approval sets `approved_credit_cents` equal to `requested_credit_cents` and records `reviewed_by_user_id`. Partial approval takes a payload `approved_credit_cents` that must be strictly less than the requested amount — anything at or above it is `ERR_CREDIT_EXCEEDS_REQUESTED` — and lands the request in `PARTIALLY_APPROVED`. Denial sets `approved_credit_cents` to zero and lands in `DENIED`. In every case the approver must differ from the BillingSpecialist who finalized or settled the cycle (`ERR_SEGREGATION_OF_DUTIES`), and approved amounts flow into the net-due recomputation of §3.7.

## 4. Endpoint Definitions

All endpoints below are mounted under the API root; nested paths are shown in full. Endpoints that create a new resource return HTTP 201; reads, state transitions, and other modifications return HTTP 200. The one exception is `raise_exception`, which returns HTTP 200 with the created ExceptionItem because it is modeled as an item state transition. The table is intentionally a summary — request payloads, response bodies, and side effects are specified by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/banks` | Create a Bank | BankOperationsAdmin |
| GET | `/banks/{bankId}` | Get a Bank | All roles |
| POST | `/banks/{bankId}/suspend` | Suspend bank posture (cascades to sites and batches) | BankOperationsAdmin |
| POST | `/banks/{bankId}/resume` | Resume bank posture | BankOperationsAdmin |
| POST | `/banks/{bankId}/liquidate` | Move the bank to LIQUIDATING (terminal) | BankOperationsAdmin |
| POST | `/banks/{bankId}/close_business_day` | Advance the logical business date; run per-day checkpoints | BankOperationsAdmin |
| POST | `/banks/{bankId}/close_analysis_cycle` | Close month-end analysis cycles (optionally one customer) | BillingSpecialist |
| POST | `/banks/{bankId}/customers` | Create a Customer | TreasuryImplementer |
| GET | `/banks/{bankId}/customers/{customerId}` | Get a Customer | All roles |
| GET | `/banks/{bankId}/customers` | List customers | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/begin_onboarding` | PROSPECT → ONBOARDING | TreasuryImplementer |
| POST | `/banks/{bankId}/customers/{customerId}/suspend` | ACTIVE → SUSPENDED (cascade) | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/resume` | SUSPENDED → ACTIVE (cascade) | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/terminate` | ACTIVE → TERMINATED | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements` | Create a ServiceAgreement | TreasuryImplementer |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}` | Get a ServiceAgreement | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/agreements` | List agreements for a customer | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/implement` | DRAFT → IMPLEMENTED | TreasuryImplementer |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/activate` | IMPLEMENTED → ACTIVE (segregation of duties; OCC) | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/suspend` | ACTIVE → SUSPENDED | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/resume` | SUSPENDED → ACTIVE | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/terminate` | ACTIVE or SUSPENDED → TERMINATED | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites` | Create a LockboxSite | TreasuryImplementer |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}` | Get a LockboxSite | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites` | List sites for an agreement | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/go_live` | PROVISIONING or SUSPENDED → LIVE | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/suspend` | LIVE → SUSPENDED | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/decommission` | LIVE or SUSPENDED → DECOMMISSIONED | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/availability_schedules` | Create an AvailabilitySchedule | TreasuryImplementer |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/availability_schedules` | List availability schedules for a site | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/availability_schedules/{scheduleId}` | Get an AvailabilitySchedule | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/availability_schedules/{scheduleId}/retire` | ACTIVE → RETIRED | TreasuryImplementer |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/transmission_formats` | Create a TransmissionFormat | TreasuryImplementer |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/transmission_formats/{formatId}` | Get a TransmissionFormat | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/transmission_formats` | List transmission formats | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/transmission_formats/{formatId}/activate` | DRAFT → ACTIVE; supersedes linked format (OCC on agreement) | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/transmission_formats/{formatId}/retire` | ACTIVE or SUPERSEDED → RETIRED | TreasuryActivator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches` | Create a RemittanceBatch (cutoff rollover computes business date) | LockboxOperator |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}` | Get a RemittanceBatch | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches` | List batches for a site | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/begin_capture` | RECEIVED → CAPTURING | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/balance` | CAPTURING → BALANCED, or OUT_OF_BALANCE on mismatch | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/force_out_of_balance` | CAPTURING → OUT_OF_BALANCE (operator override) | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/resume_capture` | OUT_OF_BALANCE → CAPTURING | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/close` | BALANCED → CLOSED (segregation: closer differs from capturer) | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/transmit` | PENDING or TRANSMISSION_FAILED → TRANSMITTED | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/acknowledge_transmission` | TRANSMITTED → ACKED | CustomerOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/mark_transmission_failed` | TRANSMITTED → TRANSMISSION_FAILED | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/items` | Capture a new RemittanceItem into the batch | LockboxOperator |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/items/{itemId}` | Get a RemittanceItem | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/items` | List items in a batch | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/items/{itemId}/accept` | CAPTURED → ACCEPTED | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/items/{itemId}/return` | CAPTURED → RETURNED | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/agreements/{agreementId}/sites/{siteId}/batches/{batchId}/items/{itemId}/raise_exception` | CAPTURED → ON_EXCEPTION (creates the ExceptionItem) | LockboxOperator |
| GET | `/banks/{bankId}/customers/{customerId}/exception_items/{exceptionItemId}` | Get an ExceptionItem | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/exception_items` | List exception items for a customer | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/exception_items/{exceptionItemId}/decide` | PENDING or ESCALATED → DECIDED (segregation: decider differs from raiser) | CustomerOperator |
| POST | `/banks/{bankId}/customers/{customerId}/exception_items/{exceptionItemId}/escalate` | PENDING → ESCALATED (one-time one-business-day extension) | CustomerOperator |
| POST | `/banks/{bankId}/customers/{customerId}/image_requests` | Create an ImageRetrievalRequest | CustomerOperator |
| GET | `/banks/{bankId}/customers/{customerId}/image_requests/{requestId}` | Get an ImageRetrievalRequest | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/image_requests` | List image requests | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/image_requests/{requestId}/fulfill` | REQUESTED → FULFILLED | LockboxOperator |
| POST | `/banks/{bankId}/customers/{customerId}/image_requests/{requestId}/deny` | REQUESTED → DENIED | LockboxOperator |
| GET | `/banks/{bankId}/customers/{customerId}/analysis_cycles/{cycleId}` | Get an AnalysisCycle | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/analysis_cycles` | List analysis cycles for a customer | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/analysis_cycles/{cycleId}/settle` | FINALIZED or DISPUTED → SETTLED (OCC) | BillingSpecialist |
| GET | `/banks/{bankId}/customers/{customerId}/analysis_cycles/{cycleId}/line_items` | List line items on a cycle | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/analysis_cycles/{cycleId}/line_items/{lineItemId}` | Get an AnalysisLineItem | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/sla_incidents` | Manually report an SLAIncident | CustomerOperator, BillingSpecialist |
| GET | `/banks/{bankId}/customers/{customerId}/sla_incidents/{incidentId}` | Get an SLAIncident | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/sla_incidents` | List SLA incidents | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/sla_incidents/{incidentId}/confirm` | REPORTED → CONFIRMED | BillingSpecialist |
| POST | `/banks/{bankId}/customers/{customerId}/sla_incidents/{incidentId}/reject` | REPORTED → REJECTED | BillingSpecialist |
| POST | `/banks/{bankId}/customers/{customerId}/error_credit_requests` | File an ErrorCreditRequest against a FINALIZED cycle | CustomerOperator |
| GET | `/banks/{bankId}/customers/{customerId}/error_credit_requests/{requestId}` | Get an ErrorCreditRequest | All roles |
| GET | `/banks/{bankId}/customers/{customerId}/error_credit_requests` | List error credit requests | All roles |
| POST | `/banks/{bankId}/customers/{customerId}/error_credit_requests/{requestId}/approve` | SUBMITTED → APPROVED (full; segregation from settler) | BillingApprover |
| POST | `/banks/{bankId}/customers/{customerId}/error_credit_requests/{requestId}/approve_partial` | SUBMITTED → PARTIALLY_APPROVED | BillingApprover |
| POST | `/banks/{bankId}/customers/{customerId}/error_credit_requests/{requestId}/deny` | SUBMITTED → DENIED | BillingApprover |
| GET | `/banks/customers/{id}` | Flat single-customer read | All roles |
| GET | `/banks/agreements/{id}` | Flat single-agreement read | All roles |
| GET | `/banks/sites/{id}` | Flat single-site read | All roles |
| GET | `/banks/transmission_formats/{id}` | Flat single-format read | All roles |
| GET | `/banks/batches/{id}` | Flat single-batch read | All roles |
| GET | `/banks/items/{id}` | Flat single-item read | All roles |
| GET | `/banks/availability_schedules/{id}` | Flat single-schedule read | All roles |
| GET | `/banks/exception_items/{id}` | Flat single-exception read | All roles |
| GET | `/banks/image_requests/{id}` | Flat single-image-request read | All roles |
| GET | `/banks/analysis_cycles/{id}` | Flat single-cycle read | All roles |
| GET | `/banks/analysis_line_items/{id}` | Flat single-line-item read | All roles |
| GET | `/banks/sla_incidents/{id}` | Flat single-incident read | All roles |
| GET | `/banks/error_credit_requests/{id}` | Flat single-error-credit-request read | All roles |
| GET | `/banks/customers` | Flat filtered list of Customers | All roles |
| GET | `/banks/agreements` | Flat filtered list of ServiceAgreements | All roles |
| GET | `/banks/sites` | Flat filtered list of LockboxSites | All roles |
| GET | `/banks/transmission_formats` | Flat filtered list of TransmissionFormats | All roles |
| GET | `/banks/batches` | Flat filtered list of RemittanceBatches | All roles |
| GET | `/banks/items` | Flat filtered list of RemittanceItems | All roles |
| GET | `/banks/availability_schedules` | Flat filtered list of AvailabilitySchedules | All roles |
| GET | `/banks/exception_items` | Flat filtered list of ExceptionItems | All roles |
| GET | `/banks/image_requests` | Flat filtered list of ImageRetrievalRequests | All roles |
| GET | `/banks/analysis_cycles` | Flat filtered list of AnalysisCycles | All roles |
| GET | `/banks/analysis_line_items` | Flat filtered list of AnalysisLineItems | All roles |
| GET | `/banks/sla_incidents` | Flat filtered list of SLAIncidents | All roles |
| GET | `/banks/error_credit_requests` | Flat filtered list of ErrorCreditRequests | All roles |
| GET | `/banks/{bankId}/customers_index` | Bank-scoped filtered list of Customers | All roles |
| GET | `/banks/{bankId}/agreements_index` | Bank-scoped filtered list of ServiceAgreements | All roles |
| GET | `/banks/{bankId}/sites_index` | Bank-scoped filtered list of LockboxSites | All roles |
| GET | `/banks/{bankId}/transmission_formats_index` | Bank-scoped filtered list of TransmissionFormats | All roles |
| GET | `/banks/{bankId}/batches_index` | Bank-scoped filtered list of RemittanceBatches | All roles |
| GET | `/banks/{bankId}/items_index` | Bank-scoped filtered list of RemittanceItems | All roles |
| GET | `/banks/{bankId}/availability_schedules_index` | Bank-scoped filtered list of AvailabilitySchedules | All roles |
| GET | `/banks/{bankId}/exception_items_index` | Bank-scoped filtered list of ExceptionItems | All roles |
| GET | `/banks/{bankId}/image_requests_index` | Bank-scoped filtered list of ImageRetrievalRequests | All roles |
| GET | `/banks/{bankId}/analysis_cycles_index` | Bank-scoped filtered list of AnalysisCycles | All roles |
| GET | `/banks/{bankId}/analysis_line_items_index` | Bank-scoped filtered list of AnalysisLineItems | All roles |
| GET | `/banks/{bankId}/sla_incidents_index` | Bank-scoped filtered list of SLAIncidents | All roles |
| GET | `/banks/{bankId}/error_credit_requests_index` | Bank-scoped filtered list of ErrorCreditRequests | All roles |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to a supplied UTC instant | BankOperationsAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_BANK_NOT_OPERATING | 409 |
| ERR_CUSTOMER_NOT_ACTIVE | 409 |
| ERR_CUSTOMER_NOT_SETTLED | 409 |
| ERR_SITE_NOT_LIVE | 409 |
| ERR_SITE_HAS_OPEN_BATCHES | 409 |
| ERR_SITE_LACKS_AVAILABILITY_SCHEDULE | 409 |
| ERR_SITE_LACKS_TRANSMISSION_FORMAT | 409 |
| ERR_BATCH_OUT_OF_BALANCE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 409 |
| ERR_TRANSMISSION_FORMAT_INACTIVE | 409 |
| ERR_EXCEPTION_ALREADY_DECIDED | 409 |
| ERR_AUTO_DECISION_IMMUTABLE | 409 |
| ERR_IMAGE_RETENTION_EXPIRED | 409 |
| ERR_INVALID_REFERENCE | 409 |
| ERR_DUPLICATE_UNIQUE_FIELD | 409 |
| ERR_CYCLE_NOT_FINALIZED | 409 |
| ERR_CYCLE_HAS_OPEN_DISPUTES | 409 |
| ERR_CREDIT_EXCEEDS_REQUESTED | 409 |
| ERR_SLA_INCIDENT_ALREADY_REVIEWED | 409 |
| ERR_ITEM_NOT_IN_CAPTURED_STATE | 409 |
| ERR_STALE_VERSION | 412 |
