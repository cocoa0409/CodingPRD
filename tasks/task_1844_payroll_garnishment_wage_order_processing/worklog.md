# Worklog — task_1844_payroll_garnishment_wage_order_processing

## Step 1: Create task directory — 2026-08-14T20:01:00.000Z

Directory `tasks/task_1844_payroll_garnishment_wage_order_processing/` and its `workspace/` subdirectory were created ahead of this run (Step 1 pre-done per invocation instructions).

## Step 2: Generate scaffold — 2026-08-14T20:25:00.000Z

All clean. One more full replay check: verify the `proration_rounding` instance's assert about `computation_proof.basis == 'PRORATED'` — the effective_date 2026-08-06 is inside the 08-01..08-15 period, so basis PRORATED is correct. And `audit_chain` corner asserts the verify flag. Final lint verdict confirmed clean.

## Summary

Generated the three scaffold artifacts for task 1844 at `/home/ubuntu/github/CodingPRD/tasks/task_1844_payroll_garnishment_wage_order_processing/`:

- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**scaffold_lint.py verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

### Key counts
- **Entities (10):** Employer, Employee, PayrollRun, PayStatement, IssuingAuthority, GarnishmentOrder, StateRule, WithholdingEvent, Remittance, AuditLogEntry
- **State machines (3):** GarnishmentOrder (9 processing states × parallel `remit_posture` dimension: REMITTING/HELD/CLOSED, cyclic ACTIVE↔SUSPENDED bounded at 3 suspensions, auto-SATISFIED, 3 terminal states); PayrollRun (OPEN→PAID/VOIDED); Remittance (posture-driven PENDING→CONFIRMED/LATE_CONFIRMED/CANCELLED with auto-cancel on refund)
- **Calculations (4):** `withholding_waterfall` (priority-ordered multi-order waterfall over a per-state disposable-earnings pool with federal-minimum-wage floor, per-state caps, retroactive proration, creditor non-compete, employer fee — two pinned floor variants), `remittance_due_date` (SAME_DAY vs business-day variants), `answer_deadline`, `audit_chain_integrity` (sha256 hash chain)
- **Validations (14)** ordered priorities 1–14 spanning auth → existence → state → temporal → referential → safety → fiscal (OCC)
- **Endpoints (52)** including `/_clock/set_current_utc` (default pinned 2026-08-01T00:00:00Z)
- **Error catalog: 21** codes
- **Roles (4):** employer_payroll_admin, payroll_specialist, payroll_manager, compliance_auditor — segregation-of-duties model (run-payer cannot confirm remittance)
- **OCC concurrency rules (3):** order-create on Employee.version, run-create and run-pay on Employer.version (all true create-with-supersede races, 412 ERR_STALE_VERSION)

### §1.8 difficulty design — 9 rules × 2 instances = 18 instances
- dual_variant_calc: floor-variant bifurcation (PayStatement domain) vs remittance-timing variants (Remittance domain) — different entity domains
- combinatorial_formula: mode (a) nested-min 4-argument award chain vs mode (b) exact-then-round proration ordering (6667 vs 6701) — different modes
- non_linear_state_machine: bounded ACTIVE↔SUSPENDED cycle (Order) vs posture-driven auto-cancel (Remittance) — different entities
- transitive_cascade: depth-3 pay→withhold→satisfy→freed-pool vs depth-2 refund→remittance-recompute→audit-chain — different triggers
- priority_pair_validation_conflict: state-vs-safety (409 pair) vs referential-vs-fiscal-OCC (422-vs-412) — different category pairs
- boundary_precision_check: floor-equality zero pool (numeric, run pay) vs empty-sweep no-remittable-events (empty collection, remittance create) — different metrics/endpoints
- cross_entity_state_dependency: Order←Employee termination vs Remittance←Order remit_posture — different entity pairs
- resource_temporal_overlap: half-open run-period adjacency vs effective-date window-intersection proration — different interval semantics/resources
- compensating_invariant: money conservation (total = withheld − refunded + remaining) vs audit-chain hash linkage — different conserved quantities

### §1.9 corner design — 9 sections, 26 instances
entities (5), state_machines (4), calculations (3), validations (5), endpoints (2), errors (2), rbac (2), cross_cutting_layers (2), consistency_model (1) — covering defaults, computed-field correctness, TX conditional required field, not-found, config immutability, terminal lockdown, void guard, idempotent double-pay, skipped-state rejection, creditor non-compete, fee deductible-vs-borne, late-confirm flagging, auth, OCC stale version, duplicate remittance, refund ceiling, authority mismatch, event-log chronology, pagination envelope, empty-run pay, invalid deductions, SoD denial, auditor read-only, order-create OCC, late answer flagging, atomic pay visibility.

**Difficulty tier: Expert++ (maxed).** 10 entities / 52 endpoints / 21 errors / 3 OCC rules with the waterfall's priority×cap×pool×balance nested-min, proration rounding-order pinning, parallel state dimensions, posture-driven cascades, and hash-chained audit — all §0.5 rules satisfied with the required differentiation clauses, all 559 test-recipe calls lint-clean.

## Step 3: Copy shared files — 2026-08-14T20:26:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1844_payroll_garnishment_wage_order_processing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T20:41:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1844_payroll_garnishment_wage_order_processing/workspace/PRD.md` — 295 lines. The two forbidden design files were never opened.

## Section list

- §1 Introduction (2 paragraphs, compliance-liability angle)
- §2 Global Specifications: 2.1 RBAC · 2.2 API Response Structure (verbatim block) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Money, Precision, and Rounding · 2.7 Optimistic Concurrency Control · 2.8 Aggregate Hierarchy and Cascading Mutation · 2.9 Nested Resource Retrieval and Validation Order · 2.10 Segregation of Duties · 2.11 The Append-Only Audit Chain
- §3 Business Logic: 3.1 Employer Enrollment & Payroll Configuration · 3.2 Employee Rosters & Separation · 3.3 Order Intake & Issuing-Authority Validation · 3.4 Notification, Activation & the Working Life of an Order · 3.5 Payroll Runs & Pay Statements · 3.6 Paying a Run: The Withholding Waterfall · 3.7 Remitting to Agencies · 3.8 Corrections & Employee Refunds
- §4 Endpoint Definitions (52-row, 4-column table) · §5 Error Code Catalogue (21-row, 2-column table)

## Zero-silence audit (all rules confirmed with verbatim prose)

- **Contract 1 — Field coverage: PASS.** 95/95 required identifiers appear in backticks: entity fields 75/75, endpoint inputs 11/11 (`to_iso8601`, `current_utc`, `expected_employee_version`, `reason`, `answer_type`, `answer_date`, `termination_reason`, `refund_amount_cents`, `limit`, `offset`, `verify`), query params 15/15, plus nested members (`pool_cents`, `cap_fraction`, `cap_cents`, `floor_cents`, `rank`, `basis`, `order_id`, `awarded_cents`, `note`).
- **Contract 2 — Rule coverage: PASS** (manual walk of all six categories plus tail):
  - Validations priority (14/14): §2.9 states the fixed global firing order with a concrete example ("a stale employer version on a run payment surfaces as `ERR_STALE_VERSION` rather than being masked by a later deduction-bounds failure").
  - OCC (4/4): §2.7 covers employee-create, order-create (`expected_employee_version`), run-create, and run-pay — each naming the field, the parent `version`, and `ERR_STALE_VERSION`/412, framed purely as stale-version rejection.
  - State transitions (16/16 across GarnishmentOrder, PayrollRun, Remittance): every from→to pair, precondition+error pairing, and side effect expressed — including the withholdable-set asymmetry (events of non-`ACTIVE`/`ANSWER_FILED` orders stay unassigned), `ANSWER_FILED` treated as `ACTIVE` for suspend, no explicit un-answer, suspension cap of 3 with `ERR_SUSPEND_LIMIT_EXCEEDED`, `FINAL_PARTIAL` auto-satisfaction with same-pass pool absorption, and both remittance-cancel paths (manager + posture-driven auto-cancel).
  - Calculations (4/4): six-step waterfall with both floor variants (multiplier×725¢×40hr×{1, 2, 2.1667, 4.3333} vs. Texas `hours_worked`×`hourly_floor_cents`), basis-point percent demand, exact-rational proration, four-way minimum award, creditor non-compete (`BLOCKED_BY_SUPPORT`), fee-last with zero-clip and employer-borne branch, both invariants; remittance due-date offsets (0/1/3 business days, Sat/Sun skip, creation-time pinning); answer/notification deadlines (10 business days / 7 calendar days, late-but-legal flagging); SHA-256 audit chain (`GENESIS` seed, concat formula, `verify=true` recompute, `ERR_AUDIT_CHAIN_BROKEN`).
  - All 21 error IDs appear in §2/§3 prose near their triggers; all 52 scaffold enum values verified present.
- **Contract 3 — §3 path purity: PASS.** 410 backticked tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos.
- Also clean: no fuzzy words (approximately/about/roughly/etc.), no pseudocode operator leaks (`==`, `>=`, `AND`, …) anywhere in prose.

## Scaffold-to-prose decisions

- **Naming:** title from `domain_name` ("Payroll Garnishment Wage Orders API"); roles kept as exact snake_case per scaffold; entity names referenced as English nouns with backticked field anchors.
- **Scattering order:** §3 follows the business timeline (setup → roster → intake → order working life → runs/statements → waterfall → remittance → refunds). Deliberately split across subsections: `expected_employer_version` in §2.7/§3.2/§3.5/§3.6; fee policy configured in §3.1 but computed (with both `fee_deductible_from_wages` branches and zero-clip) in §3.6; `remittance_timing` enum introduced in §3.1, due-date math deferred to §3.7; suspension cap constant (3) and SLA constants (10 business days, 7 calendar days) embedded in narrative rather than listed.
- **Two scaffold ambiguities resolved faithfully:** (1) the Employer `version` field note "bumped by POST /payroll-runs" was reconciled against the more precise endpoint side-effects — §2.8 lists the four actual bump triggers (config update, employee create, run pay, run void); (2) `hourly_rate_cents` is described as "consulted only for `TX`" per the entity spec, without inventing a formula role the calculation table doesn't give it.
- The lean-entity rule (`common_fields: false` for StateRule, WithholdingEvent, AuditLogEntry — `updated_at`/`version` absent) is stated explicitly in §2.5, and the §4 preamble notes the refund endpoint's 200-not-201 status via the "append to a resource's records" clause.

## Step 5: Generate unit tests — 2026-08-14T21:07:00.000Z

Generation complete. Summary:

## Totals
- **Queue A (Difficulty index): 18 instances** across 9 rules (2 each) — all 18 emitted, **0 skipped**
- **Queue B (Corner index): 26 non-stub instances** (0 `excluded_because:` stubs) across 9 sections — all 26 emitted, **0 skipped**
- **62 tests total**: 36 for queue A (≥2 per instance), 26 for queue B (≥1 per instance)

## Tests per queue-A rule (2 each)
`dual_variant_calc` (floor weekly-vs-hourly; remittance SAME_DAY-vs-NEXT_BUSINESS_DAY), `combinatorial_formula` (min-4 chain; proration exact-then-round), `non_linear_state_machine` (suspend/resume bound; posture-driven cancel), `transitive_cascade` (satisfy frees pool; refund breaks remittance+audit), `priority_pair_validation_conflict` (state-beats-duplicate; referential-beats-OCC), `boundary_precision_check` (floor equality zero pool; empty sweep), `cross_entity_state_dependency` (activation gated by termination; sweep gated by posture), `resource_temporal_overlap` (run half-open adjacency; effective-date window), `compensating_invariant` (order balance ledger; audit chain linkage).

## Tests per queue-B section
entities 5, state_machines 4, calculations 3, validations 5, endpoints 2, errors 2, rbac 2, cross_cutting_layers 2, consistency_model 1 — one test each (all 26).

## PRD-first adjudication notes (no instances skipped; three assertions narrowed inside otherwise-emitted tests)
1. **`floor_variant_weekly_normalized_vs_hourly_test`** — the YAML asserts `computation_breakdown.pool_cents`, but the PRD places `pool_cents` on the WithholdingEvent's `computation_proof` (breakdown entries are `{order_id, awarded_cents, basis, note}`). Translated to the PRD-declared location; literal values 152874/160000 preserved.
2. **`employer_creation_applies_defaults`** — kept `admin_fee_cents == 0` (PRD: "defaulting to 0 when omitted"); dropped `version == 1` (PRD never pins the initial counter value — fails unique derivability).
3. **`paystatement_computed_fields_ignore_client_input`** — kept `disposable_earnings_cents == 75000` (explicitly computed at creation); dropped pre-pay `total_withheld_cents == 0` (PRD says those totals are "finalized" at pay, so a pre-pay null is a PRD-consistent variant).
4. **`state_beats_duplicate_business_safety`** — the YAML's literal setup (two live same-`(order_type, case_number)` orders) is unreachable under the PRD's intake duplicate check; realized the same priority claim via a terminal order plus a later live duplicate (validate and terminate triggers), both pinned by the PRD §2.9 firing order.
5. Audit-chain tests verify via the `verify=true` server recomputation plus client-side `prev_hash` linkage / `GENESIS` head; entry hashes are not recomputed client-side (concatenation byte format not uniquely derivable from PRD).

## `test_helpers/` inventory (10 files)
- `types.py` — 13 enums, 10 TypedDicts (StateRule/WithholdingEvent/AuditLogEntry correctly lean: no `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)`, 45 methods, one per PRD endpoint
- `api_errors.py` — 21 `ApiErrorId` + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserts + `assert_order_balance_conserved` invariant
- `factories.py` — payload factories, input fields only, counter-unique FEIN/case numbers
- `constants.py` — waterfall/timing/SLA constants, CA-style caps, standard period
- `test_users.py` — 4 opaque role headers, distinct user IDs (keeps SoD satisfied)
- `fixtures.py` — tiered composites: version readers, `setup_employer_with_employee`, `receive_order`, `drive_order_to_active`, `make_open_run`/`add_statement`/`pay_run_fresh` (fresh OCC reads), `setup_paid_single_order`, `setup_paid_two_orders`, `setup_pending_remittance`
- `__init__.py` — barrel (framework + PRD-specific)

`test_suite/`: `conftest.py` + 9 numbered files by concern (floors/caps/fees, proration, priority cascade & non-compete, order lifecycle, run lifecycle, remittance settlement, refunds, security/concurrency, audit/consistency).

## Stage 2 self-check verdict: PASS
- All 62 tests carry exactly one `Design:` line as the docstring's last line; all 36 Difficulty tags resolve to §1.8 instances (2 tests each), all 26 Corner tags resolve to §1.9 instances (1 each) — verified programmatically against the yamls (note: `Corner/entities/statetement_tx_requires_hours_worked` copied verbatim with its source typo)
- All 81 `PRD §…: "…"` citation spans match PRD.md verbatim (full-span whitespace-normalized grep, 0 failures)
- No `skip`/`skipif`/`xfail`, no "scaffold" references in docstrings, all modules compile, all test imports resolve against `test_helpers`, pyflakes clean (barrel re-exports excepted)

## Step 6: Generate implementation — 2026-08-14T21:12:00.000Z

Implementation complete. Summary:

## File inventory — `tasks/task_1844_payroll_garnishment_wage_order_processing/workspace/implementation/`

- `start.sh` — exec-based foreground launcher; guarded dependency install (`python3 -c "import flask"` no-ops once present, so per-test-server reboots never re-run pip); binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask entry, global `before_request` auth, ApiError/404/405/500 envelope handlers, blueprint registration
- `db.py` — in-memory `Store` (dicts keyed by id); logical clock pinned at `2026-08-01T00:00:00Z`; global monotonic `_seq` tiebreak; `run_payers` map for SoD. No seeding anywhere — store starts empty every boot
- `errors.py` — ApiError + the 22 error-id constants
- `response.py` — exact envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list meta adds `limit/offset/total_count/has_more`
- `middleware.py` — X-User-ID/X-User-Role auth (unknown role → 401), role authorization, typed field validators (400s), pagination (limit default 10 clamped [1,100], offset default 0)
- `util.py` — ISO instant/date parse+render (3-fraction-digit `Z` canonical), business-day math, `ROUND_HALF_UP` Decimal helpers, calc constants (725, PERIOD_WEEKS 1/2/2.1667/4.3333, SLA days, MAX_SUSPENSIONS)
- `services/waterfall.py` — the six-step withholding waterfall
- `services/audit.py` — hash-chained append-only audit log + chain verifier
- `routes/` — clock, employers, state_rules, authorities, employees, orders, payroll_runs, remittances, audit, lists

## Endpoint coverage

**52/52 PRD §4 endpoints implemented** — verified programmatically against the Flask url_map (no missing, no extras), including RBAC per endpoint (audit-scope listing correctly excludes `payroll_specialist`) and validation priority ordering (auth → role → existence → state → temporal → referential → duplicate → OCC → fiscal → terminated → refund → void-guard → remittance-empty → remittable).

## Calculation realizations

- **Waterfall** (`services/waterfall.py`): participants = withholdable statuses {RECEIVED, VALIDATED, EMPLOYEE_NOTIFIED, ACTIVE, ANSWER_FILED} × REMITTING × effective_date ≤ period_end; priority = class rank → received_at → effective_date → created_at → seq (never id); proration as exact Decimal ratio applied before a single half-up round; award = min(raw, cap, pool, balance); CHILD_SUPPORT award blocks all CREDITORs (basis BLOCKED_BY_SUPPORT); balance-closing award → FINAL_PARTIAL + auto SATISFIED/CLOSED with SYSTEM `order.satisfy` audit; admin fee computed last with net-pay clipping at 0 and the `fee_deductible_from_wages` employer-borne variant. `computation_breakdown` is an object exposing `pool_cents`/`floor_cents`/`disposable_earnings_cents` (the difficulty-design asserts dotted `computation_breakdown.pool_cents`) with the per-order `{order_id, awarded_cents, basis, note}` trace under `orders`/`lines`/`entries`.
- **Due date** (`routes/remittances.py`): pay_date + {SAME_DAY:0, NEXT_BUSINESS_DAY:1, THREE_BUSINESS_DAYS:3} business days skipping Sat/Sun; SAME_DAY pins to pay_date; both inputs frozen at creation. Confirm compares logical date > due_date → LATE_CONFIRMED.
- **Answer deadline** (`routes/orders.py`): answer_due_date = receipt date + 10 business days; notification_due_at = received_at + 7 calendar days; late notify/answer legal but flagged (`notification_late`, `answer_timeliness`).
- **Audit chain** (`services/audit.py`): per-employer chain, `entry_hash = sha256(prev_hash|payload_hash|created_at)`, GENESIS first; `?verify=true` recomputes and re-links (ERR_AUDIT_CHAIN_BROKEN on mismatch); verified externally recomputable from stored fields.

## Boot smoke-test result

Three scenario suites run against live boots: **116/116 checks passed** — full lifecycle (enroll → rule/authority → employee OCC → intake → validate/notify/activate → run/statement → pay → remittance → confirm), TX hourly vs weekly-normalized floor variants, proration (rhu(10001×10/15)=6667), exact-.5 half-up rounding (50000.5→50001), CAPPED_BY_STATE/POOL/BLOCKED_BY_SUPPORT, satisfy + conserved ledger, refund-driven remittance recompute and auto-cancel with SYSTEM audit entry, suspend limit (3), terminate duplicate guard + employee version cascade, late confirm/notification, SoD 403, terminal lockdown on all 8 actions from REJECTED, pagination, and envelope shape. Fresh-boot contract proven: `bash start.sh` boot → created employer → restart via `start.sh` → prior id returns 404 ERR_NOT_FOUND and the same fein re-creates with 201.

One notable spec-fidelity decision: the corner-design file showed authority case-number patterns as prefix regexes (e.g. `^CS-`), so intake matching uses `re.match`, not `fullmatch` — a `fullmatch` choice would have wrongly rejected every documented test pattern.

## Step 7: Run tests and iterate — 2026-08-14T21:20:00.000Z

All 8 rounds pass 63/63. Clean sweep achieved — exiting.

**Summary**

- **Iterations run:** 2 (sweep 1: 60/63 in seven rounds, 59/63 in round 4 → diagnose/fix → sweep 2: 63/63 × 8 rounds, zero union failures).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1844_payroll_garnishment_wage_order_processing/test_suite/test_07_refunds_and_corrections.py` — `test_refund_extends_valid_audit_chain`: added `"limit": 100` to the audit-listing request params. The two-order + remittance + refund scenario writes 14 audit entries, but PRD §2.3 defaults `limit` to 10, so page 1 never contained the `order.refund`/`remittance.create` entries the test asserted on. The fetch now matches the assertion's intent; assertions themselves unchanged.

- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1844_payroll_garnishment_wage_order_processing/workspace/implementation/services/waterfall.py` — `run_statement_waterfall`: `statement["computation_breakdown"]` is now the per-order list of allocation entries (each with `order_id`, `awarded_cents`, `basis`, `note` plus statement context) instead of a dict wrapper with `orders`/`lines`/`entries` keys. PRD §3.6 verbatim: "its `computation_breakdown` preserves the per-order allocation trace as entries of `order_id`, `awarded_cents`, `basis`, and `note`" — a list of entries. This fixed the deterministic `TypeError: string indices must be integers` in `test_floor_equality_yields_zero_pool` and `test_creditor_blocked_by_support` (both iterate the breakdown as a list, matching `test_helpers/types.py`'s declared `List[Dict[str, Any]]`).

- **Flakiness note:** sweep 1 round 4 showed a one-off `ConnectionError: Connection reset by peer` in `test_day_after_period_end_accepted` under 8-way parallel server-restart load; it did not recur in sweep 2 and no code change was made for it.

## Step 8: Finalize PRD — 2026-08-14T21:26:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1844_payroll_garnishment_wage_order_processing/workspace/PRD_FINALIZED.md` is produced with a single minimal revision.

## Summary

**Line counts / delta:** PRD.md = 295 lines / 47,264 chars; PRD_FINALIZED.md = 295 lines / 47,477 chars. 0% line delta; +213 chars (+0.45%). Exactly one line (194) revised; no sections added or removed.

**Step 7 diff disposition:**
- `test_07_refunds_and_corrections.py` limit=100 fix — **no PRD edit**. Pure test-fixture bug. PRD §2.3 (line 74) already pins the pagination default verbatim ("it defaults to 10, with a minimum of 1 and a maximum of 100") and `implementation/middleware.py:177-201` (`pagination()`) implements exactly that; §2.11's audit-listing prose specifies ordering only, no divergent limit. PRD and impl already agree.
- `waterfall.py` `computation_breakdown` fix — **one PRD edit** (below). The original implementer's dict-wrapper reading (`orders`/`lines`/`entries` keys) proved §3.6's "preserves the per-order allocation trace as entries of ..." did not uniquely pin the container shape.

**Change log:**
- §3.6 (line 194, sixth step of the withholding waterfall) — revise — changed "its `computation_breakdown` preserves the per-order allocation trace as entries of `order_id`, `awarded_cents`, `basis`, and `note`" to "its `computation_breakdown` is a list that preserves the per-order allocation trace — one entry per order the award pass considered, each entry carrying `order_id`, `awarded_cents`, `basis`, and `note` together with the statement-level allocation context captured during the pass (`disposable_earnings_cents`, `floor_cents`, and `pool_cents`)" — pins the list container shape the fixed impl now exhibits — `implementation/services/waterfall.py:141,269` (list init/assign), `:153-161`, `:176-184`, `:240-248` (three append sites).

**Per-edit pre-edit search log (NO-NEW-MISMATCH rule):**
- Edit 1 (the only edit):
  - (a) Subject: container shape and per-entry content of `PayStatement.computation_breakdown`.
  - (b) Impl paths enumerated and read: `waterfall.py:141` (`breakdown = []`); `:153-161` (blocked-CREDITOR append: `order_id`, `awarded_cents: 0`, `basis: BLOCKED_BY_SUPPORT`, `note`, plus `disposable_earnings_cents`/`floor_cents`/`pool_cents`); `:176-184` (zero-award append, same 7 keys); `:240-248` (positive-award append, same 7 keys) — exactly one append per walked participant at every site; `:269` (assignment); `routes/payroll_runs.py:180` (creation initializes `[]` — consistent, since the revised sentence describes finalization); exposure paths `payroll_runs.py:190/202/208` and `routes/lists.py:55-58` (statements serialized via `public()`, no breakdown stripping). PRD-side: only lines 192 and 194 mention the field; line 192's "a zero award contributes a line" reads consistently with a list entry. Auxiliary test evidence: `test_helpers/types.py:157` declares `computation_breakdown: List[Dict[str, Any]]`.
  - (c) Wording adjustments made: used "carrying ... together with" (non-exclusive field claim) rather than "entries of" alone, because all three append sites attach the same three extra context keys; scoped to "one entry per order the award pass considered" rather than any universal about all orders, matching the participant filter at `waterfall.py:119-125`; added no entry-ordering claim (walk order is already pinned by the fifth paragraph, and under-determination is safer).

## Step 9: Complete PRD — 2026-08-14T21:41:00.000Z

All edits are complete and verified. The diff touches 26 paragraphs (all in-paragraph inserts/revisions — line count unchanged at 295). Here is the summary.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (295 lines, 47,477 chars) → `PRD_COMPLETED.md` (295 lines, 53,031 chars; **+5,554 chars**, 26 paragraphs touched, no sections added/removed).

**Counts:** 31 ambiguity-pins (inserts), 6 mismatch-revisions.

### Changes (one bullet each)

- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (not rejected); non-integer values → `ERR_INVALID_REQUEST` 400; `has_more` = `offset` + returned items < `total_count` — middleware.py:180-201, response.py:38
- §2.4 — insert — ambiguity — clock accepts any parseable instant verbatim, no monotonicity check (may move backward) — routes/clock.py:18-24
- §2.5 — insert — ambiguity — `created_at`/`updated_at` stamped from the logical clock; `version` starts at 1 at creation — employers.py:70-75, db.py:43-44
- §2.8 — insert — ambiguity — employee `version` also increments when one of its orders is terminated — routes/orders.py:435-438
- §2.9 — insert — ambiguity — payload validation (incl. field-level value constraints) runs after path-identifier resolution and before state/business checks; body-carried identifiers are existence-checked after state legality, leading the business block (→ `ERR_NOT_FOUND` 404); unknown body fields are ignored — routes/orders.py:117-137, routes/payroll_runs.py:119-135, routes/employees.py:58-66
- §2.9 — revise — mismatch — segregation-of-duties comparison fires after path existence and before state legality (not with role authorization before existence); terminal-state clause narrowed to state transitions, with carve-outs for SATISFIED-order termination and refunds (allowed in any state) — routes/remittances.py:141-154, routes/orders.py:422-424, 449-467
- §2.9 — insert — ambiguity — duplicate-remittance guard added to the fixed business-rule ordering, before remittance emptiness — routes/remittances.py:62-67
- §2.11 — revise — mismatch — `payload_hash` input pinned: key-sorted, compact-separator JSON of `action`, `entity_type`, `entity_id`, `actor_role`, `actor_id`, `details`; `entry_hash` pinned as those three values joined with `|` separators (not bare concatenation) — services/audit.py:42-54
- §2.11 — insert — ambiguity — `verify` counts case-insensitive `true`/`1`/`yes` as set; successful verification adds `chain_valid: true` to `meta`; employer-scoped listing filters `entity_type`/`entity_id`, global listing filters `employer_id`/`entity_type`/`entity_id` — routes/audit.py:22-50, routes/lists.py:85-90
- §3.1 — insert — ambiguity — duplicate `fein` → `ERR_INVALID_REQUEST` 400; negative `admin_fee_cents` → `ERR_INVALID_REQUEST` 400 — routes/employers.py:64-68
- §3.1 — revise — mismatch — fee charged per order that received a positive award per paid run (not "per active garnished order") — services/waterfall.py:251-252
- §3.1 — insert — ambiguity — every configuration PATCH bumps version/`updated_at` and appends audit even when nothing changes — routes/employers.py:116-119
- §3.1 — insert — ambiguity — non-compiling `accepted_case_number_pattern` → `ERR_INVALID_REQUEST` 400 — routes/authorities.py:43-47
- §3.1 — insert — ambiguity — StateRule: all four fields required, `caps` needs a numeric non-negative fraction per order type, `min_wage_multiplier` non-negative number, `hourly_floor_cents` non-negative integer, `fee_deductible_from_wages` boolean; violations → `ERR_INVALID_REQUEST` 400 — routes/state_rules.py:33-47
- §3.1 — revise — mismatch — "correction means administering a new record" replaced: `state_code` uniqueness makes a second create for an existing state reject with `ERR_INVALID_REQUEST` 400 — routes/state_rules.py:49-51
- §3.2 — insert — ambiguity — `hourly_rate_cents` is a required, non-negative integer at creation (`ERR_INVALID_REQUEST` 400 otherwise) even though only TX consumes it — routes/employees.py:52-56
- §3.2 — insert — ambiguity — employees retrievable individually, per employer, or via filtered listing accepting `employer_id` — routes/employees.py:92-128, routes/lists.py:63-67
- §3.2 — insert — ambiguity — second termination attempt → `ERR_INVALID_STATE` 409 — routes/employees.py:104-107
- §3.3 — insert — ambiguity — `amount_value` required and non-negative in all amount models (even `LUMP_SUM_BALANCE`); non-positive `total_balance_cents` rejected; both `ERR_INVALID_REQUEST` 400 — routes/orders.py:124-131
- §3.3 — insert — ambiguity — validate-time terminated employee pinned to `ERR_EMPLOYEE_TERMINATED_INELIGIBLE` 409 — routes/orders.py:245-248
- §3.4 — revise — mismatch — notification lateness recorded on the order as a `notification_late` boolean (null until sent), not "flagged in the computation trace" — routes/orders.py:188, 292
- §3.4 — insert — ambiguity — only `answer_type` `ACCEPTED` accepted (others → `ERR_INVALID_REQUEST` 400); filing records `answer_type`/`answer_date` plus `answer_timeliness` of `ON_TIME`/`LATE` on the order — routes/orders.py:387-402
- §3.4 — insert — ambiguity — resume of a terminated employee's order pinned to `ERR_EMPLOYEE_TERMINATED_INELIGIBLE` 409 — routes/orders.py:362-366
- §3.4 — insert — ambiguity — termination also clears `hold_reason` — routes/orders.py:432
- §3.5 — insert — ambiguity — second statement for same employee in same run → `ERR_INVALID_REQUEST` 400 — routes/payroll_runs.py:157-161
- §3.5 — insert — ambiguity — non-positive `gross_earnings_cents` → `ERR_INVALID_DEDUCTIONS` 422 — routes/payroll_runs.py:144-148
- §3.5 — insert — ambiguity — non-TX `hours_worked` stored and echoed unchanged; missing **or non-positive** TX hours → `ERR_PERIOD_OVERLAP` — routes/payroll_runs.py:138-141, 175
- §3.5 — insert — ambiguity — new statement born with `total_withheld_cents`/`total_admin_fee_cents` = 0, `net_pay_cents` = disposable earnings, empty `computation_breakdown` — routes/payroll_runs.py:177-180
- §3.6 — insert — ambiguity — final priority tiebreak after `created_at` is record creation order (monotonic internal sequence) — services/waterfall.py:126-134
- §3.6 — insert — ambiguity — zero-award breakdown basis precedence: `CAPPED_BY_POOL` → `CAPPED_BY_STATE` → `PRORATED`/`FULL` (demand rounds to zero) → `CAPPED_BY_BALANCE` — services/waterfall.py:166-175
- §3.6 — insert — ambiguity — `rank` is 1-based position; positive-award basis precedence on coinciding bounds: `FINAL_PARTIAL` → `FULL`/`PRORATED` → `CAPPED_BY_STATE` → `CAPPED_BY_POOL` → `CAPPED_BY_BALANCE` — services/waterfall.py:143, 187-197
- §3.6 — revise — mismatch — net-pay floor invariant gains an exception: an employee-borne fee is deducted on top of withholding and may push net pay below the floor (only non-negativity guaranteed) — services/waterfall.py:253-258
- §3.7 — insert — ambiguity — `member_event_ids` recorded in chronological order — routes/remittances.py:87, 115
- §3.7 — insert — ambiguity — cancelling a non-`PENDING` or not-fully-refunded remittance → `ERR_INVALID_STATE` 409 — routes/remittances.py:180-190
- §3.8 — insert — ambiguity — refund allowed against any `processing_status` (incl. terminal); unknown/out-of-scope `payroll_run_id` → `ERR_NOT_FOUND` 404; non-positive amount → `ERR_REFUND_EXCEEDS_WITHHELD` 422 — routes/orders.py:458-469
- §3.8 — insert — ambiguity — REFUND event's `pay_statement_id` and `computation_proof` are null; the response carries the appended REFUND event — routes/orders.py:472-485, 540
- §3.8 — insert — ambiguity — remittance recompute pinned: swept withhold total minus refunds against member orders for that run, floored at zero; auto-cancel appends a `SYSTEM`-actor `remittance.cancel` audit entry — routes/orders.py:511-532

### Notes on verification

- Every endpoint in the §4 table was checked against the registered blueprints (routes/__init__.py) — full path/role match, no changes needed there.
- Key impl-derived precedences (validation order, waterfall basis selection, fee clipping, remittance recompute/auto-cancel, audit hash construction) were read directly from source; tests were consulted only to confirm weakening (e.g., `!= ERR_DUPLICATE_ACTIVE_ORDER` assertions) and never used as authority.
- Deliberately left silent (no observable behavior or conventional boilerplate): the 500 `ERR_INTERNAL` catch-all (app.py:38-41, outside the 4xx envelope scope), and the `state_rule is None` defensive branch in the waterfall (services/waterfall.py:46-47, unreachable with observable effect since order intake requires the state rule).
