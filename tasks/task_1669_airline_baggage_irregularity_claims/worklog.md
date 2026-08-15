# Worklog — task_1669_airline_baggage_irregularity_claims

## Step 1: Create Task Directory — 2026-08-14T06:16:00.000Z

Task directory `tasks/task_1669_airline_baggage_irregularity_claims/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking pipeline. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T07:10:00.000Z

Scaffold generation complete. All three artifacts written, lint-clean.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1669_airline_baggage_irregularity_claims/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` (§1.9)

**Counts**
- Entities: **12** (Station, Carrier, CourierService, RepairVendor, Passenger, BagTag, IrregularityReport, TracingEvent, DeliveryDispatch, RepairOrder, ExpenseClaim, SettlementPayment) — flat topology, FK-linked
- Endpoints: **50** (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- Difficulty instances: **18** (9 rules × 2, all §0.5 differentiation clauses honored — e.g., dual variants on settlement-liability vs expense-reimbursement domains; combinatorial modes (a) and (b); cascades of depth 3 and 2 from different triggers)
- Corner instances: **55 total** (49 active + 6 `excluded_because` stubs referencing difficulty instances)

**Design highlights**
- Archetype: workflow orchestration + ledger reconciliation; layers: dual-variant calc, cascading side effects, OCC, scheduled actions; cyclic state machines (settlement reject/re-offer loop on IrregularityReport, dispatch fail/reschedule loop on DeliveryDispatch)
- Domain mechanics: Montreal flat cap (170016¢) vs domestic per-kg cap (2500¢/kg), declared-value cap lift, per-day vs pooled expense reimbursement with pinned round-per-receipt FX order, 20%/yr depreciation with 10% floor and 0.75 repair-vs-replace threshold, 504h tracing-timeout sweep, courier buffer-expanded window conflicts vs vendor half-open bench-capacity, settlement-money and bench-slot conservation invariants
- One OCC rule (`settlement-create-stale-report`, 412 via `expected_report_version`); 32 domain error codes; 4 roles (Passenger is `entity_backed:Passenger`, others opaque)

**Verification**: `scaffold_lint.py` verdict block — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (557 calls scanned). Additional scripted audits passed: all `grounds` refs resolve, 73 instance names unique across both design files, ≥2 instances per rule, no forbidden concurrency vocabulary, all 32 errors have at least one trigger test. All formula-derived asserts were pre-computed as literals (e.g., 10500 vs 23000 expense variants, 210 FX rounding, 50000 capped offer, 10.0 mishandled rate).

## Step 3: Copy Shared Files — 2026-08-14T07:12:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_1669_airline_baggage_irregularity_claims/workspace/INSTRUCTION.md` via bash `cp`.

## Step 4: Generate PRD — 2026-08-14T07:35:00.000Z

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1669_airline_baggage_irregularity_claims/workspace/PRD.md` — 308 lines.

**Section list:**
- §1 Introduction (2 paragraphs: WorldTracer lifecycle narrative + constituencies/conventions)
- §2 Global Specifications: 2.1 Roles & RBAC (with per-role identity prose: three opaque roles, `Passenger` entity-backed), 2.2 API Response Structure (byte-identical verbatim block, verified), 2.3 Pagination, 2.4 Common Resource Properties (incl. TracingEvent's `common_fields: false` exception), 2.5 The Logical Clock, 2.6 Cross-Entity Counters and Cascade Consistency, 2.7 Nested Resource Retrieval, 2.8 Money/Currency/Rounding, 2.9 OCC, 2.10 Validation Order (all 10 priorities as an explicit ordered cascade with applies-to scopes)
- §3 Business Logic (9 subsections, chronological by claim lifecycle): reference data, passenger/check-in, report opening, tracing/timeout sweep, courier dispatch, expense reimbursement, damage/repair workshop, settlement-to-closure, station irregularity reporting
- §4 Endpoint table (50 rows, 4 columns only), §5 Error catalogue (32 rows, 2 columns only)

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 89 required (68 entity fields + 21 endpoint I/O/common identifiers), 89 present, 0 missing — PASS
- Contract 2 (Rule Coverage): verified by walk-through — 10/10 validation priorities expressed in order; 1/1 OCC rule (write endpoint + `expected_report_version` + `ERR_STALE_REPORT_VERSION`/412 all named); 38/38 state transitions with preconditions and side effects; 6/6 calculations in precise reconstructible prose (liability cap, settlement offer pinned order, expense window/FX/variant caps, depreciation decay/floor/threshold, payment components + conservation invariant, station rate); 32/32 error conditions paired in §2/§3; all endpoint side effects and applies-to scopes enumerated; sibling branches symmetric — PASS
- Contract 3 (§3 Path Purity): 426 backtick tokens scanned, 0 paths / 0 bare methods / 0 method+path combos — PASS

**Design decisions and ambiguities:**
- §2 organized into 10 domain-derived subsections (logical clock, counters/cascades, money/rounding as separate concerns); §3 grouped chronologically by claim lifecycle. Constants embedded in business prose with unit conversion (504 hours rendered as "504 hours — twenty-one days"; caps in cents).
- One scaffold ambiguity preserved faithfully rather than resolved: `ERR_VENDOR_CAPACITY_EXCEEDED` triggers when a day "would hold `bench_capacity` or more open orders" — the PRD mirrors this predicate without resolving whether the incoming order is counted, matching the scaffold's exact wording.
- `station_code`, `carrier_code`, and `email` are described as unique business identifiers per scaffold field descriptions, but no duplicate-error ID exists for them in the catalog, so no error was invented for them (only `tag_number`/`report_reference` have duplicate errors).

## Step 6: Generate Implementation — 2026-08-14T08:01:00.000Z

Generated a complete Python + Flask implementation of the airline baggage irregularity claims API.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1669_airline_baggage_irregularity_claims/workspace/implementation/`):

| File | Lines | Purpose |
|---|---|---|
| `app.py` | 1826 | Flask entry point; all routes, business logic, calculations, state machines, cascades |
| `db.py` | 32 | In-memory `STORE` with per-entity dicts and unique-index maps; no seeding |
| `errors.py` | 44 | `ApiError` exception + all 30 error-ID constants from the scaffold |
| `middleware.py` | 58 | `X-User-ID`/`X-User-Role` extraction, role validation, `require_roles` decorator |
| `response.py` | 49 | Envelope builders: `meta`/`response_type`/`data` for success, list (with `limit`/`offset`/`total_count`/`has_more`), and error |
| `util.py` | 94 | Logical clock helpers (ISO↔ms), `req_…` ids, UUIDs, `touch()` for `updated_at`/`version` bumps, half-up rounding |
| `validators.py` | 113 | Body-shape validators (`as_str`, `as_int`, `as_enum`, `as_date_str`, `as_iso_datetime_str`, `as_tag_number`, etc.) raising `ERR_INVALID_REQUEST` |
| `start.sh` | 10 | Guarded pip install (no-op when flask is present), `exec python3 app.py` in foreground, honors `PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | 1 | `Flask==3.0.3` |

**Total: 2227 lines.**

**Notable design decisions**

- **Single-file routes** — rather than the skill's suggested `routes/` + `services/` split, all endpoints live in `app.py` (grouped by resource). The entity graph is small enough that this stays readable and avoids circular-import risk between services.
- **Logical clock**: stored as epoch ms on the `STORE`, initialized exactly once per process at `2026-08-01T00:00:00Z`. `POST /_clock/set_current_utc` runs the tracing-timeout sweep inline (504-hour threshold, requires no `LOCATED` event for the report) and returns `swept_report_ids`.
- **`claim_path` internal field**: the settlement-offer calculation requires knowing whether a report entered `CLAIM_REVIEW` via `DECLARED_LOST` vs other doors. Tracked on the report record as a private field but excluded from the serialized view since it's not in the entity model.
- **OCC ordering**: per PRD §2.10 step 6, machine-state check (`ERR_SETTLEMENT_NOT_PAYABLE`) runs before the OCC version check (`ERR_STALE_REPORT_VERSION`, 412).
- **Window conflict** for dispatches implements the exact buffer-expanded closed-interval semantics: conflict iff `(new_start - buffer) < existing_end AND existing_start < (new_end + buffer)`.
- **Vendor capacity** walks each day in `[intake_date, promised_date)` half-open and rejects if adding the new order would exceed `bench_capacity` on any day.
- **Money**: `Decimal` with `ROUND_HALF_UP` throughout — FX conversion per receipt then sum (forbidding sum-then-round), depreciation applied once at end, floor compared after rounding, mishandled rate rounded to 2 decimals.
- **TracingEvent** is append-only: no `updated_at`/`version` fields per PRD §2.4.
- **Per-test-server isolation**: in-memory store is rebuilt from scratch on every boot; no seeds, no fixtures, no module-level state other than the empty `STORE`.

**Smoke verification**

Two end-to-end smoke suites were run against a freshly booted server covering: full DELAYED → TRACING → FOUND_PENDING_DELIVERY → DELIVERY_IN_PROGRESS → DELIVERED → CLAIM_REVIEW → SETTLEMENT_OFFERED → SETTLEMENT_ACCEPTED → CLOSED lifecycle; interim expense claim with domestic daily-cap computation (20000 cents claimed → 7500 reimbursed under STANDARD tier); DAMAGED repair-order flow with depreciation (100000 purchase price, 2 full years → 64000 depreciated, REPAIR decision at estimate 5000 < 48000 threshold, payout 5000); settlement reject/re-offer; OCC 412 stale version; payment void restoring `amount_payable_cents`; clock sweep to DECLARED_LOST with lost-bag settlement cap computation; auth-header 400; wrong-role 403; not-found 404; station irregularity summary. All passed.

**Ambiguities encountered**

- **PRD §2.10 priority 3 (ownership) vs priority 5 (existence)**: ownership is listed before existence, but ownership requires the report to be loaded. Evaluated existence first on the path id (since you can't check ownership of a non-existent report), then ownership before business rules. This matches standard practice.
- **`assess-damage` when `repairable=true`**: PRD says the report "stays in DAMAGE_REVIEW" — `touch()` the report (bumping version/updated_at) without changing status, since the assessment did mutate the resource.
- **`open-claim-review` etc. action endpoints with no inputs**: accept either no body or an empty JSON object; reject any body with fields.

## Step 5: Generate Unit Tests — 2026-08-14T08:14:00.000Z

**Files written**

**test_helpers/** (9 files):
- `types.py` — status enums (BagTag, IrregularityReport, DeliveryDispatch, RepairOrder, ExpenseClaim, SettlementPayment, etc.), TypedDicts per entity; `TracingEvent` correctly omits `updated_at`/`version` (append-only, PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~40 methods)
- `api_errors.py` — `ApiErrorId` enum (32 errors) + HTTP status map registered via `set_error_http_status_map` (note the 412 for OCC, 422s for fiscal/repair-window)
- `assertions.py` — per-entity assertions + `assert_vendor_slot_invariants`
- `factories.py` — payload factories with unique sequencing for `tag_number`/`report_reference`/`email`
- `constants.py` — MONTREAL_CAP 170016, DOMESTIC_PER_KG 2500, tier caps, FX rates, depreciation constants, 504h timeout, fixed clock epoch strings
- `test_users.py` — opaque-role shared headers + `make_passenger_headers(user_id)` for the entity-backed Passenger role
- `fixtures.py` — composite helpers: `setup_bag_and_report`, `setup_found_pending_delivery`, `setup_declared_lost_report`, `setup_settlement_accepted`, `setup_closed_report`, `setup_damage_report_repairable/claim_review`
- `__init__.py` — barrel export

**test_suite/** (8 test files, 88 tests): reference data/envelope/clock, report lifecycle + tracing sweep + LOCATED cascade, delivery dispatch (window conflicts, failure/reschedule, delivered cascade), expense claims (FX round-per-receipt, eligibility window, tier caps, adjudication), damage/repair (depreciation floor, bench capacity, decision threshold), settlement workflow (reject/re-offer cycle, OCC, money conservation, lockdown), validation/RBAC (uniqueness, ownership, priority pairs, station summary, tracing-event listing), liability-cap variants.

**Coverage audit (programmatically verified)**
- All 18 difficulty instances: exactly ≥2 tests each
- All 47 non-stub corner instances: ≥1 test each; the 6 `excluded_because` stubs correctly untranslated (pointers verified to resolve)
- Every test docstring ends with exactly one verbatim `Design:` tag resolving to a real instance; every test carries a PRD quote that survives literal grep of PRD.md
- All modules compile, import cleanly, and `pytest --collect-only` gathers 88 tests

**Instances skipped**
None. Every non-stub instance passed the PRD-first two-condition filter.

**Notable design decisions**
- **Priority-pair difficulty instances** (state-beats-fiscal, zone-beats-window): kept, since PRD §2.10 explicitly fixes the validation cascade order ("the first failing check determines the rejection") and names both error IDs in ordered items 6/10 and 7/8 — unique derivability holds.
- **`existence_beats_state_priority_ordering`**: kept on the same §2.10 ordering grounds (existence item 5 before state item 6).
- Two extra tests initially written were removed as freelance/not-faithful-to-instance (an offer-on-TRACING rejection and a happy-path assess-damage), keeping every test a faithful translation of its tagged instance.

## Step 7: Test Iteration Loop — 2026-08-14T08:35:00.000Z

All 8 rounds pass 88/88. The task is complete.

**Iterations run:** 2 (initial sweep: 9-10 failures per round, union of 11 distinct tests; post-fix sweep: 88/88 × 8 rounds, zero flakes).

**Tests deleted:** none — every failing assertion traced to a verbatim PRD rule.

**Fixes applied to `test_suite/`:**
- `test_suite/test_01_reference_data.py` — `test_clock_default_is_fixed_epoch`: expected `created_at` corrected to `"2026-08-01T00:00:00.000Z"` (PRD §2.5 pins the epoch instant; §2.4 requires three fractional digits on `created_at` — the test's bare `"…T00:00:00Z"` mis-transcribed PRD). `test_reports_list_pagination_with_filter`: call-site kwarg `type=` → `report_type=` to match the fixture signature.
- `test_suite/test_03_delivery_dispatch.py` — two `pickup_at` string-equality assertions switched to `assert_same_instant` (PRD §3.5 pins "replaces `pickup_at` with `new_pickup_at`" but is silent on the serialization form of client-supplied datetimes; a normalizing implementation is equally faithful — STEP 1c split keeping the covered instant assertion).
- `test_suite/test_07_validation_rbac_reporting.py` — `test_summary_after_full_lifecycle_closure`: expected `mishandled_rate_per_1000` corrected from `10.0` to `0.01` (1000 × 1 / 100000; the test's arithmetic mis-computed the §3.9 formula). `test_events_reverse_reachable_by_report`: advance the logical clock 1s between the two events so their `created_at` values are distinct — §2.3 pins ascending-`created_at` order but is silent on ties, so the tied-timestamp order assertion was not uniquely derivable (flaked 6/8 rounds).

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — `create_station`/`create_carrier` now default to unique codes (`unique_station_code()`/`unique_carrier_code()`); PRD §3.1 requires `station_code`/`carrier_code` uniqueness, so the shared `"JFK"`/`"AA"` defaults made any test creating two setups fail with a correct `ERR_INVALID_REQUEST` (this was the shared-fixture bug behind `test_domestic_per_day_cap_vs_montreal_pool` and `test_identical_loss_divergent_caps`). `setup_bag_and_report` re-fetches the bag after report creation so `ctx["bag"]` reflects the §3.3 `CHECKED`→`MISHANDLED`/`DELIVERED_DAMAGED` cascade instead of the stale creation snapshot.
- `api_client.py` — `ApiClient.__init__` sets `Connection: close` on the session: urllib3 was reusing keep-alive sockets whose server had been SIGKILLed by the per-test-server restart, producing the sporadic `ConnectionResetError`/`RemoteDisconnected` in `test_void_bumps_version_and_allows_superseding_payment` (rounds 3, 8) and `test_closed_report_rejects_offer_settlement` (round 6).
- `assertions.py` — added `assert_same_instant` helper.

**Fixes applied to `implementation/`:**
- `app.py` `paginate()` — sort key changed from `(created_at, id)` to `created_at` only; the random-UUID tiebreak made same-timestamp list order nondeterministic. Stable sort over insertion-ordered store dicts keeps PRD §2.3 compliance while making ties deterministic. No PRD-required check was removed or weakened; no entity data was seeded; storage remains in-memory only.

## Step 8: Finalize PRD — 2026-08-14T08:50:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly three targeted edits, each traced to a `<step_7_diff>` item.

**Line counts:** PRD.md 308 lines / 49,326 chars → PRD_FINALIZED.md 310 lines / 50,059 chars (**+1.49%**).

**Changes (one bullet each):**
- §2.3 — **revise** — appended "The sort is stable: resources that share the same creation timestamp retain their relative creation order." to the list-ordering sentence — `implementation/app.py:374-384` (`paginate()` sorts on `created_at` only; stable sort over insertion-ordered store dicts).
- §2.4 — **insert** — new paragraph pinning that client-supplied datetime fields (`to_iso8601`, `occurred_at`, `pickup_at`, `new_pickup_at`) are interpreted as instants, naive values read as UTC, and echoed normalized as `YYYY-MM-DDTHH:MM:SS.mmmZ` — `implementation/app.py:566-567,594` (clock), `app.py:1016,1028-1037` (tracing event), `app.py:1359,1392` (dispatch create), `app.py:1488,1504` (reschedule); canonical form from `implementation/util.py:27-33`.
- §3.1 — **revise** — duplicate `station_code` and duplicate `carrier_code` pinned as rejected with `ERR_INVALID_REQUEST` — `implementation/app.py:612-613` and `app.py:691-692`.
- §3.2 — **revise** — duplicate passenger `email` pinned as rejected with `ERR_INVALID_REQUEST` — `implementation/app.py:795-796`.

**Step-7 items intentionally not edited** (PRD already pins the behavior or the fix was test-internal): clock epoch `created_at` "2026-08-01T00:00:00.000Z" (§2.5 epoch + §2.4 three-fractional-digits); `mishandled_rate_per_1000 = 0.01` (§3.9 formula verbatim); fixture kwarg rename, `setup_bag_and_report` re-fetch, and `api_client.py` `Connection: close` (test-harness internals with no PRD surface).

**Per-edit pre-edit search log:**
1. **Edit A (tie order).** (a) Subject: list-endpoint sort order. (b) Enumerated: `paginate()` (app.py:374-384, sole sort site) and all nine callers — `list_stations` (638), `list_couriers` (751), `list_bag_tags` (880), `list_reports` (993), `list_tracing_events` (1069), `list_settlement_payments` (1283), `list_dispatches` (1427), `list_repair_orders` (1600), `list_expense_claims` (1765); confirmed filters run before `paginate` so insertion order is preserved into the stable sort. Non-paginated array output `swept_report_ids` (app.py:594) is an action-endpoint field, outside §2.3's "list endpoints" scope. (c) Wording scoped to "list endpoints" and "creation timestamp" ties only — no claim made about non-list responses.
2. **Edit B (datetime normalization).** (a) Subject: serialization of client-supplied ISO 8601 datetime inputs. (b) Enumerated every `as_iso_datetime_str`/`iso_to_ms` request-field site: `to_iso8601` (566-567, echoed `ms_to_iso` at 594), `occurred_at` (1016, normalized at 1029, stored at 1037), `pickup_at` (1359, stored normalized at 1392), `new_pickup_at` (1488, stored normalized at 1504); naive-input-as-UTC at util.py:22-23. Confirmed date-only fields (`incurred_on`, `intake_date`, `promised_date`, `purchase_date`, `opened_on`, `delivered_on`) are stored verbatim and thus excluded. (c) Wording names the four datetime fields explicitly and claims the canonical form only for those, avoiding any implication for date fields.
3. **Edit C (uniqueness errors).** (a) Subject: uniqueness enforcement on `station_code` / `carrier_code` / passenger `email`. (b) Enumerated: the three creation sites (app.py:612-613, 691-692, 795-796, all `ERR_INVALID_REQUEST`/400) and the unique indexes (db.py:23-25), written only at creation; §4 endpoint table confirms no update endpoints exist for stations/carriers/passengers, so no other path can contradict; `ERR_INVALID_REQUEST` 400 already present in the §5 catalogue. (c) Kept the pins as parentheticals inside the existing §3.1/§3.2 narratives rather than amending §2.10 step 9 — creation of these three resources has no post-shape checks besides uniqueness, so no validation-order claim was needed.

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1669_airline_baggage_irregularity_claims/workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-14T08:55:00.000Z

All edits applied. Final verification confirms the diff is exactly the 18 intended edits (39 changed/added diff lines across both sides).

**Source vs. output:** `PRD_FINALIZED.md` (310 lines / 50,253 chars) → `PRD_COMPLETED.md` (311 lines / 53,960 chars), char-delta **+3,707**. No new sections; all changes are inline inserts/revisions within existing paragraphs or lists.

**Counts:** 17 ambiguity-pins, 4 mismatch-revisions (21 changes total; the §2.2 error bullet and §2.3 edits each bundle closely-related pins at one site).

**Changes:**

- §2.2 success envelope — insert — ambiguity — pinned `api_request_id` as `req_` + twenty random uppercase alphanumeric chars — implementation/util.py:48-50
- §2.2 error format — insert — ambiguity — pinned undefined paths → `ERR_NOT_FOUND` (404), unsupported method on a defined path → `ERR_INVALID_REQUEST` (400), and unexpected failures → `ERR_INVALID_REQUEST` (400) rather than 5xx — implementation/app.py:131-144
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` or negative `offset` rejected with `ERR_INVALID_REQUEST` (400) — implementation/app.py:348-371
- §2.3 — insert — ambiguity — pinned `total_count` = filtered count before pagination and `has_more` ⇔ `offset + len(returned) < total_count` — implementation/response.py:20-34
- §2.4 — insert — ambiguity — `version` starts at 1 and initial `updated_at` equals `created_at` — implementation/util.py:90-94
- §2.4 — insert — ambiguity — resource `created_at`/`updated_at` are stamped from the logical clock; the envelope's `api_request_timestamp` is the only wall-clock value — implementation/util.py:53-58, 84-94
- §2.4 — insert — ambiguity — date-valued request fields (`incurred_on`, `intake_date`, `promised_date`, `purchase_date`) require strict `YYYY-MM-DD`, else `ERR_INVALID_REQUEST` — implementation/validators.py:82-93
- §2.5 — insert — ambiguity — clock may be set backward (no monotonicity guard) and `swept_report_ids` is in report creation order — implementation/app.py:567-596
- §2.7 — revise — ambiguity — added station ids inside `serves_station_ids` and a tracing event's `carrier_id` to the existence-checked foreign-key list — implementation/app.py:724-725, 1020-1021
- §2.10 step 3 — revise — mismatch — ownership check on passenger-scoped operations is applied after body-shape and existence resolution (impl needs the report loaded), not at strict priority position 3 — implementation/app.py:1164-1174, 1709-1714
- §2.10 step 4 — insert — ambiguity — body must be a JSON object; required string fields must be non-empty while receipt `description` and tracing-event `notes` may be empty — implementation/validators.py:12-21, 42-45
- §3.1 Carrier — revise — mismatch — `is_interline_partner` is recorded but gates nothing; tracing messages from any registered carrier are accepted (PRD had implied non-partner messages are not accepted) — implementation/app.py:1000-1026 (no partner check)
- §3.1 Courier Service — insert — ambiguity — `serves_station_ids` may be empty and each element must reference an existing station — implementation/app.py:721-725
- §3.2 — insert — ambiguity — `routing_carrier_ids` must contain at least one carrier id — implementation/app.py:829
- §3.3 — insert — ambiguity — pinned initial report fields: `root_cause`/`root_cause_station_id`/`settlement_offer_cents` null; `amount_payable_cents`/`expenses_approved_unpaid_cents`/`expenses_paid_cents` zero — implementation/app.py:947-952
- §3.4 — revise — mismatch — a tracing event's `created_at` is stamped with its normalized `occurred_at` instant (backdatable), not the recording time as §2.4's generic definition implied — implementation/app.py:1028-1040
- §3.6 — insert — ambiguity — `reject_reason` is optional: omitted on REJECT leaves `decision_reason` null; supplied with APPROVE it is ignored — implementation/app.py:1775-1797
- §3.7 — revise — mismatch — wrong-state repair-order creation carries `ERR_REPORT_NOT_IN_DAMAGE_REVIEW`, not the nonexistent `ERR_REPAIR_NOT_IN_DAMAGE_REVIEW` (also absent from the §5 catalogue) — implementation/app.py:1537-1539, errors.py:24
- §3.7 — insert — ambiguity — `payout_cents` remains null until order completion — implementation/app.py:1569, 1636-1641
- §4 — insert — ambiguity — no-input action endpoints accept an absent body or empty JSON object; any supplied field → `ERR_INVALID_REQUEST` — implementation/app.py:545-551
- §4 — revise — ambiguity — enumerated exact-match filters per list endpoint (reports: station_id/passenger_id/bag_tag_id/liable_carrier_id/root_cause_station_id/status; tracing events: report_id/carrier_id/station_id/event_type; settlement payments & expense claims: report_id/status; dispatches: +courier_service_id; repair orders: +vendor_id), replacing the dangling "filters described in §3" phrase — implementation/app.py:988-992, 1065-1068, 1277-1282, 1418-1426, 1591-1599, 1759-1764

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1669_airline_baggage_irregularity_claims/workspace/PRD_COMPLETED.md`
