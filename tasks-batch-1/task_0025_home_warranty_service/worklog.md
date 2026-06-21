# Worklog — task_0025_home_warranty_service

## Step 1: Create task directory — 2026-05-28T00:00:00Z

Created `./tasks/task_0025_home_warranty_service/workspace/`.

## Step 2: Generate scaffold — 2026-05-28T01:16:00Z

Scaffold artifacts generated successfully.

**Files written:**
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0025_home_warranty_service/SCAFFOLD.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0025_home_warranty_service/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0025_home_warranty_service/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts (SCAFFOLD.yaml §1.1–§1.7):**
- Entities: 7 (ContractPackage, Customer, Contract, CoveredItem, ClaimTicket, Dispatch, RenewalReminder)
- State machines: 3 (Contract, ClaimTicket, Dispatch)
- Calculations: 6 (provisional_copay, final_copay, is_return_visit, service_fee_charged, renewal_premium, contract_payout_aggregate)
- Validations: 14 (ordered by priority)
- Endpoints: 31 (including 2 test-driving `/_clock/*`)
- Errors: 14
- Roles: 5 (Anonymous, Customer, Dispatcher, Technician, PlatformAdmin)
- Concurrency rules: 1 (OCC on Contract.version for renewal)

**Design entries:**
- §1.8 difficulty design: 18 active instances across all 9 `rule_id` groups (2 per rule — meets §0.5 minimum exactly)
- §1.9 corner design: 38 entries (30 active, 8 `excluded_because:` stubs that reference §1.8 instances) across 9 sections matching the claim-extraction-guide taxonomy

**Complexity profile selected:** pricing_engine + compliance_audit, flat topology, cyclic state machine shape (ClaimTicket reopen edge), peer_roles, immediate consistency. Layers: dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, scheduled_deferred_actions, optimistic_concurrency.

**Linter verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (487 calls scanned, 0 violations across all six lint checks a–f).

## Step 3: Copy INSTRUCTION.md — 2026-05-28T01:18:00Z

Copied `./INSTRUCTION.md` → `./tasks/task_0025_home_warranty_service/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-28T01:22:00Z

**Output:** `workspace/PRD.md`

**Stats**
- Line count: 272
- Top-level sections: 5 (§1 Introduction, §2 Global Specs, §3 Business Logic, §4 Endpoints, §5 Errors)
- §2 subsections: 10 (2.1 RBAC, 2.2 Response Envelope, 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Nested Resource Retrieval, 2.6 Validation Priority, 2.7 OCC, 2.8 Monetary Precision, 2.9 Cascading Side Effects, 2.10 Coverage Window + In-Period Aggregate)
- §3 subsections: 9 (3.1 Catalog & Onboarding, 3.2 Contract Activation Cycle, 3.3 Covered Items & Pre-Existing Exclusion, 3.4 Claim Filing & Triage, 3.5 Dispatch & Return-Visit Guarantee, 3.6 Resolution & Reopening, 3.7 Co-Pay Computation, 3.8 Renewal Cycle & Premium, 3.9 Admin Test-Driving)

**Hard Contracts**
- Field coverage: 53/53 fields present (PASS)
- Rule coverage: 14/14 validations, 1/1 OCC, 15/15 state transitions, 6/6 calculations, 14/14 error mappings, 32/32 endpoint side-effects (PASS)
- Path purity (§3): 276 backticked tokens scanned; 0 `/` paths, 0 bare HTTP methods (PASS)

**Notable scattering / layout decisions**
- Validation priority in own §2.6 subsection (14 rules).
- Coverage window + in-period aggregate paired in §2.10 (shared half-open `[coverage_start_utc, coverage_end_utc)` interval).
- Co-pay formula in §3.7 with provisional triggers in §3.4 (assessment) and final triggers in §3.5 (dispatch).
- Renewal-premium calculation embedded in §3.8 renewal lifecycle (per-item rounding-order + 15-day discount boundary).
- Test-driving clock wrapped into §3.9 narrative ("why time matters" — 30-day reminder, 365-day window, return-visit window).
- §3 path purity via state-transition + role+verb framing.

## Step 5: Generate unit tests — 2026-05-28T03:40:00Z

All good. Stage 1 and Stage 2 are complete.

## Summary

Generated complete test infrastructure for `task_0025_home_warranty_service`:

**Stage 1 — test_helpers/** (9 files, ~1320 lines):
- `types.py` — entity TypedDicts (mutable: ContractPackage, Customer, Contract, CoveredItem, ClaimTicket, Dispatch; append-only: RenewalReminder), status/role enums
- `api_client.py` — one method per PRD §4 endpoint
- `api_errors.py` — 14 error IDs registered with the framework's HTTP-status map
- `assertions.py` — per-entity shape validators
- `factories.py` — per-entity payload builders with `**overrides`
- `constants.py` — PRD-stated thresholds
- `test_users.py` — TEST_USERS shared constants plus per-instance `make_customer_headers(customer_id)` for the only entity-backed role
- `fixtures.py` — five tiers of composite setup (clock, package/customer, contract, claim lifecycle, full-lifecycle shortcuts and contract auto-transition states); identity threading through `make_customer_headers(customer["id"])` everywhere ownership is gated
- `__init__.py` — barrel export of framework generics + PRD-specific code

**Stage 2 — test_suite/** (14 test files + conftest, ~2310 lines, 66 test functions):
- 9 difficulty files (`test_01`…`test_09`), one per rule_id in queue A — each instance covered by exactly 2 tests, 18 instances total → 36 tests
- 5 corner files (`test_10`…`test_14`) covering all 30 non-stub queue-B instances → 30 tests; 7 `excluded_because:` stubs were verified to cross-reference real Difficulty instances and were NOT translated

**Audit results:**
- Every difficulty instance has ≥2 tagged tests (verified by `grep | sort | uniq -c`)
- Every non-stub corner instance has ≥1 tagged test
- Every docstring ends with `Design: Difficulty/<rule_id>/<instance.name>` or `Design: Corner/<section>/<instance.name>` as the final non-empty line (verified programmatically)
- All PRD citations are verbatim quotes pulled from `PRD.md` (modulo wrap whitespace, per skill C1)
- Every `from test_helpers import …` symbol resolves to a barrel export (verified programmatically)
- All 23 Python files parse cleanly
- No instances were skipped — every queue-A instance and every non-stub queue-B instance passed the PRD-first two-condition filter and was translated

**Files produced:**
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0025_home_warranty_service/test_helpers/` (9 files)
- `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0025_home_warranty_service/test_suite/` (15 files: conftest + 14 test_*.py)

## Step 6: Generate implementation — 2026-05-28T03:40:00Z

Clean.

Implementation summary:

**Files generated** under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0025_home_warranty_service/workspace/implementation/`:
- `start.sh` (executable, foreground, exec-handoff, PORT env, 0.0.0.0)
- `requirements.txt` (flask==3.0.3)
- `app.py` — Flask entry point, blueprint registration, exception handlers
- `db.py` — In-memory stores, UUID/timestamp helpers, logical-clock state
- `errors.py` — APIError class + all 14 error_id constants verbatim from scaffold §1.6
- `response.py` — Exact `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination
- `middleware.py` — `X-User-Role`/`X-User-ID` extraction, role gating
- `routes/`: contract_packages, customers, contracts, covered_items, claims, dispatches, renewal_reminders, clock
- `services/`: validation, calculations (Decimal + ROUND_HALF_UP), aggregates, ownership

**Key design decisions / findings**:
1. **Logical-clock timestamps for entities** — `stamp_common`/`bump`/`stamp_immutable` write `created_at`/`updated_at` from the server logical clock (`now_logical_iso()`), not wall-clock. This keeps the half-open coverage-window aggregate filter (`coverage_start_utc <= ClaimTicket.created_at < coverage_end_utc`) consistent with the coverage bounds, which are themselves stamped from the logical clock. Wall-clock `now_iso()` is reserved for `api_request_timestamp` in the response meta envelope.
2. **Calculations use `Decimal` with `ROUND_HALF_UP`** — `copay_share_pct` is converted via `Decimal(str(pct))` to avoid IEEE-754 noise; surcharge follows mode-(b) rounding order (round per-item first, then multiply by extra_items), exactly as pinned in scaffold §1.3 renewal_premium.
3. **Return-visit comparison is strict** — `T < L + W*86400` (boundary exclusive), matched verbatim in `services/calculations.is_return_visit`.
4. **Tech double-book uses strict `< 3600s`** — exact 60-min gap is permitted.
5. **Validation priority** — auth (1) → roles (2) → path-id existence (3) → FK existence (4) → cross-aggregate (5) → state (6) → pre-existing (7) → coverage window (8) → capacity (9) → scheduled-past (10) → double-book (11) → open-claims-block-cancel (12) → OCC (13) → body shape (14). State check fires before OCC on renew (priority 6 < 13) — matches scaffold §1.4.
6. **No startup seeding** — all stores start empty; the harness drives state via the declared API surface.
7. **Resolve picks latest dispatch on claim** — after reopen + redispatch a claim has multiple Dispatch rows; `resolve` picks the most recently created (`max(created_at)`) and requires it be `COMPLETED`.

**Verified via end-to-end smoke testing**:
- Anonymous customer registration → admin package creation → contract creation/activation
- CoveredItem registration with capacity enforcement
- Claim filing → assess (provisional copay) → dispatch (SF + return-visit pinning) → start → complete (CoveredItem cascade) → resolve (final copay + contract aggregate recomputation)
- Return-visit window: 2nd dispatch within 14-day window → `is_return_visit=True`, `service_fee_charged_cents=0`, `prior_dispatch_id` populated
- Final co-pay variants: first-visit-over-cap (`12500`), return-visit-over-cap (`3000`)
- Renewal: clock tick fires `ACTIVE → EXPIRING_SOON` with reminder + `days_to_expiry=17`; renew with correct OCC produces successor with `108000` premium (10% discount, D=17, 1 item)
- Surcharge: 3 items late renewal → `52000` (no discount + 2 × 1000 per-item)
- OCC mismatch returns 412 `ERR_STALE_VERSION`
- Double-booking at 30-min interval returns 422 `ERR_TECHNICIAN_DOUBLE_BOOKED`; exact 60-min permitted
- Pre-existing exclusion blocks `/assess` with 422 `ERR_PRE_EXISTING_EXCLUDED`
- Reopen cycle: `DISPATCHED → ASSESSED` with `provisional_copay_cents` reset; subsequent dispatch correctly re-evaluates `is_return_visit` against prior `last_dispatch_completed_utc`
- `start.sh` boots cleanly via `bash start.sh` and responds in <3s

## Step 7: Test + diagnostic fix loop — 2026-05-28T03:55:00Z

All 8 rounds report `passed == total` (66/66) with zero failures, errors, or skips. The earlier confusion was because my inspection script used the wrong field name (`outcome` vs `status`); every test actually has `status == "passed"`. Exiting per the cardinal rule that no iteration is needed when all 8 rounds are green.

Summary:

- **Iterations run:** 1 (single 8-round parallel sweep).
- **Round results:** 8/8 rounds clean — every round reports `passed=66, total=66, failed=0, errors=0, skipped=0`.
- **Tests deleted:** None.
- **Fixes applied to `test_helpers/`:** None.
- **Fixes applied to `implementation/`:** None.

Result artifacts (one per round) at `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0025_home_warranty_service/workspace/implementation/results.{1..8}.json`. Total wall time for the parallel sweep: ~6 minutes.

## Step 8: Finalize PRD — SKIPPED — 2026-05-28T03:55:00Z

Skipped per skill rule: Step 7 exited on first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. PRD.md already determined every behavior the implementation exhibits at the Step-7-visible sites.

## Step 9: PRD completeness scan — 2026-05-28T04:05:00Z

All edits are in-paragraph, line count unchanged (272 ↔ 272), char delta +3690.

## Summary

**Source:** `PRD.md` (no `PRD_FINALIZED.md` present) → `PRD_COMPLETED.md`

**Line counts:** 272 → 272 (unchanged; all inserts in-paragraph)
**Char delta:** +3,690 (41,059 → 44,749)

**Counts:** 14 ambiguity-pins, 0 mismatch-revisions (impl is consistent with PRD prose; gaps are all silence, not contradiction)

**Per-change log:**

- §3.1 (package code) — insert — ambiguity — pin code regex to `^[A-Z]{3,16}$` and pin duplicate-code error to `ERR_INVALID_REQUEST` — `routes/contract_packages.py:56-58`, `services/validation.py:110-120`
- §3.1 (package retire) — insert — ambiguity — pin that retiring an already-`RETIRED` package returns `ERR_INVALID_STATE` — `routes/contract_packages.py:101-102`
- §3.1 (customer registration) — insert — ambiguity — pin that auth headers supplied on `POST /customers` are ignored, pin email shape to `local@domain.tld`, pin duplicate-email to `ERR_INVALID_REQUEST`, pin `full_name` / `home_address` to non-empty strings — `routes/customers.py:26-39`, `services/validation.py:99-105`
- §3.2 (contract open) — insert — ambiguity — pin that a `Customer` caller opening for someone else's `customer_id` returns `ERR_FORBIDDEN` — `routes/contracts.py:62-64`
- §3.2 (activate) — insert — ambiguity — pin that activation from any state other than `PENDING_PAYMENT` returns `ERR_INVALID_STATE`, and clarify premium pinning only when existing value is zero — `routes/contracts.py:134-135, 151-152`
- §3.2 (cancel) — insert — ambiguity — pin that cancel from `EXPIRING_SOON`/`EXPIRED`/`CANCELLED`/`RENEWED` returns `ERR_INVALID_STATE`, and that non-owner Customer cancel returns `ERR_FORBIDDEN` — `routes/contracts.py:167-169`, `services/ownership.py:20-24`
- §3.3 (covered-item creation) — insert — ambiguity — pin that no contract-state guard applies to `POST /covered-items`, and that `install_year` upper bound is the host wall-clock UTC year (not the logical clock) — `routes/covered_items.py:51-54`
- §3.3 (pre_existing_flag) — insert — ambiguity — pin that `pre_existing_flag` must be JSON boolean (string/number/etc. → `ERR_INVALID_REQUEST`), and that `null` defaults to false — `routes/covered_items.py:56-59`, `services/validation.py:58-61`
- §3.5 (dispatch payload) — insert — ambiguity — pin `scheduled_utc` must be a parseable ISO 8601 string (else `ERR_INVALID_REQUEST`), and that an exact equality with the clock is allowed — `services/validation.py:84-94`, `routes/claims.py:259`
- §3.6 (resolve) — insert — ambiguity — pin "the Dispatch linked to the claim" as the most-recently-created Dispatch row by `created_at` ascending, so reopen-and-redispatch resolves on the latest row — `routes/claims.py:341-347`
- §3.6 (reopen) — insert — ambiguity — pin same latest-by-`created_at` rule for reopen eligibility check — `routes/claims.py:389-395`
- §3.8 (renew payload) — insert — ambiguity — pin that non-`EXPIRING_SOON` renew returns `ERR_INVALID_STATE`, non-owner Customer renew returns `ERR_FORBIDDEN`, missing/non-int `expected_contract_version` returns `ERR_INVALID_REQUEST`, `null` for `new_package_id` is treated as omitted, and a non-existent `new_package_id` returns `ERR_NOT_FOUND` before the retired check — `routes/contracts.py:197-223`
- §3.8 (renewal premium) — insert — ambiguity — pin that negative `days_remaining` (clock past `coverage_end_utc`) is permitted and falls into the no-discount branch — `routes/contracts.py:229-234`, `services/calculations.py:110-115`
- §3.9 (clock-tick) — insert — ambiguity — pin contract iteration order to `created_at` ascending, and pin the per-contract priority: past-`coverage_end_utc` jumps straight to `EXPIRED` (no reminder; `renewal_reminder_sent_at` stays null), otherwise the 30-day `ACTIVE → EXPIRING_SOON` reminder fires — `routes/clock.py:64-124`

Output file: `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0025_home_warranty_service/workspace/PRD_COMPLETED.md`
