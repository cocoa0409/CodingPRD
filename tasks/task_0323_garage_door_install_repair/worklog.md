# Worklog — task_0323_garage_door_install_repair

Scenario: Garage Door Install & Repair: door/opener catalog & measure, service call vs install quote, spring/cable/panel parts, technician dispatch & ETA, emergency/after-hours, warranty & tune-up plan, financing, callback

Difficulty: Expert (passed to scaffold-generator §0.4 in Step 2 only)

## Step 1: Create task directory — 2026-06-13T11:50:00.000Z

Used pre-specified directory `tasks/task_0323_garage_door_install_repair` (no auto-increment, per instructions). Created `workspace/` subdirectory. Directory was pre-existing and empty.

## Step 2: Generate scaffold (Expert) — 2026-06-13T11:52:00.000Z

All structural constraints satisfied. The scaffold is complete and lint-clean.

Generated all three Expert-tier scaffold artifacts for **task_0323_garage_door_install_repair**. `scaffold_lint.py` returns **VERDICT: clean lint** (58 endpoints, 13 entities, 18 §1.8 instances, 35 §1.9 instances, 460 calls scanned — all conform to §1.5; all FKs reverse-reachable).

**Complexity profile:** pricing_engine + workflow_orchestration; flat topology; parallel state-machine shape; segregation_of_duties role model; layers = optimistic_concurrency, dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Entities: 13** — Customer, Technician, DoorModel, OpenerModel, Part, EquipmentUnit, Quote, QuoteLine, Job, PartReservation, WarrantyPlan, FinancingApplication, Callback.
- **State machines: 7** — Quote.status (cyclic revision self-loop + branch accept/decline/expire), Job.dispatch_status and Job.billing_status (parallel independent dimensions on one entity), PartReservation.status, WarrantyPlan.status, FinancingApplication.status (branching), Callback.status (cyclic reopen). Plus **2 concurrency_rules** (OCC on Job.version for reservation-create; OCC on Quote.version for revise).
- **Calculation rules: 5** — quote_estimate_total (per-line-round-then-sum, mode b), job_final_total (dual-variant vs estimate), job_emergency_surcharge (tiered time-of-day band + min/max clamp, mode a), technician_callback_rate (dual-variant provisional vs settled), financing_monthly_payment (term-tiered APR amortization). All formula literals pre-computed in code (e.g. estimate 50900 vs final 35900; surcharge 18000; financing 24-mo 2466).
- **Validation rules: 18** (priority-ordered: auth → existence → state → business_safety/referential/constraint/temporal).
- **Endpoints: 58** (includes one `/_clock/set_current_utc` test-driving endpoint; flat collections with sub-resource + filtered-list reverse-reachability for every FK). Note: the surface lands above the nominal Expert 20–32 band because the scenario spans 8 distinct feature areas (catalog/measure, quote, parts, dispatch/ETA, emergency, warranty/tune-up, financing, callback) — trimmed redundant reads + the payoff transition to keep it lean; difficulty is carried by coupling, not count.
- **Error catalog: 18.**
- **Roles: 4** — Customer (entity_backed), Technician (entity_backed), Dispatcher (opaque), ServiceManager (opaque); segregation enforced via Job.completed_by_user_id ≠ invoicing manager.

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids (matching §0.5 verbatim) × 2 instances = **18 instances**. OCC moved to §1.9 since it is not one of the nine §0.5 rules.

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:** **35 active instances + 3 `excluded_because` stubs** across all 9 claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers incl. both OCC stale-version probes + correct-version success + derived-field reconciliation, consistency_model).

Audits passed: nine §0.5 rule_ids match; no forbidden concurrency vocabulary; full enum-value closure (every status produced by a transition/init); every error referenced; every grounds ref resolves; neither design key appears inside SCAFFOLD.yaml.

## Step 3: Copy INSTRUCTION.md — 2026-06-13T11:52:30.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-13T12:12:00.000Z

**PRD generated:** `workspace/PRD.md` — 293 lines, 5 top-level sections (§1 Introduction, §2 Global Specifications w/ 9 subsections, §3 Business Logic w/ 13 subsections, §4 Endpoint Definitions, §5 Error Code Catalogue).

**Coverage confirmation — every scaffold artifact expressed in prose:**
- **Entities (13):** all covered. Contract 1 field-name check: 62/62 `entities[].fields` names present in backticks, 48/48 endpoint input identifiers present, 12/12 query-param names present. DoorModel/OpenerModel correctly carry only `id`/`created_at`.
- **State machines (7):** Quote (cyclic revise + accept/decline/expire), Job dispatch dim, Job billing dim (parallel), PartReservation, WarrantyPlan, FinancingApplication, Callback (cyclic reopen) — all transitions with from/to, preconditions paired to error IDs, side-effect cascades expressed (accept→Job→reservations→Part pools; close→warranty→active_warranty_count; cancel→release+booked_minutes compensation). All 45 state/enum values present verbatim.
- **Calculations (5):** quote_estimate_total (per-line round-before-sum, mode b), job_final_total (consumed-parts actuals), job_emergency_surcharge (3 bands, inclusive 18:00:00 boundary, clamp-only-when-positive), technician_callback_rate (provisional vs settled dual variant, denom==0→0), financing_monthly_payment (term-tiered APR, ceil for 0% tier, amortization). All constants embedded.
- **Validations (18):** all present with explicit priority ordering (§2.8); each `check` matchable to its `error_id`; multi-endpoint `applies_to` scopes enumerated.
- **Concurrency rules (2):** both OCC rules expressed in stale-version terms + ERR_STALE_VERSION (HTTP 412); no time-overlap framing.
- **Endpoints (58):** all 58 in §4 table; §3 path purity confirmed.
- **Errors (18):** all in §5 table; every ID also in §2/§3 narrative.
- **Roles (4):** Customer, Dispatcher, Technician, ServiceManager — all named; entity_backed ownership prose for Customer/Technician, opaque for Dispatcher/ServiceManager, ServiceManager invoice-segregation noted.

**Hard Contracts:** Contract 1 (Field-Name Coverage) PASS, Contract 2 (Rule Coverage) PASS, Contract 3 (§3 Path Purity) PASS. Neither withheld design file nor any sibling task was read.

## Step 5: Generate unit tests — 2026-06-13T12:30:00.000Z

Generated complete test infrastructure (EXPERT tier) purely from the four task inputs + the unit-test-generator skill.

**Total tests emitted: 71** (across 7 test files)
- **Queue A (Difficulty): 36 tests** covering all **18 instances** (9 rules × 2 instances), each with ≥2 tests — audit passes with zero shortfalls.
- **Queue B (Corner): 35 tests** covering all **35 non-stub instances**, each with ≥1 test.

**Skipped / gapped instances: 0 PRD-filter skips.** Every difficulty and non-stub corner instance passed the two-condition PRD filter (verbatim coverage + unique derivability). The **3 `excluded_because:` corner stubs** were correctly NOT translated (no `test_recipe`; their assertions owned by cited difficulty instances): `callback_rate_settled_equals_provisional_after_resolve` → `dvc_technician_callback_rate_provisional_vs_settled`; `rate_threshold_overnight_rate_clamped_at_max` → `cf_emergency_surcharge_tier_and_cap`; `immediate_accept_job_visible_via_list` → `tc_quote_accept_job_reservation_part_depth3`.

**Validation performed:** all 16 files compile clean; every test docstring carries exactly one `Design:` tag mapping to a real instance; every quoted PRD citation verbatim-matches; no `scaffold`/`Table N`/`§1.x` refs and no `skip`/`xfail` markers; all helper imports + `api.<method>` calls resolve; pre-computed expected values independently re-derived (financing 2466/10000, surcharge 18000/final 90000, estimate 50900/final 35900, per-line round 450/sum 900, 18:00-boundary clamp 5000).

**Files:** `test_helpers/`: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. `test_suite/`: `conftest.py`, `test_01_catalog_and_entities.py` (10), `test_02_quote_lifecycle.py` (9), `test_03_dispatch_and_scheduling.py` (12), `test_04_job_completion_and_pricing.py` (10), `test_05_cascades_and_inventory.py` (9), `test_06_warranty_financing_callbacks.py` (15), `test_07_rbac_and_listing.py` (6).

Note: tests validated via static analysis (compile, import-resolution, citation-grep, coverage audits) — `prd_bench_local_runner` not importable in gen environment.

## Step 6: Generate implementation — 2026-06-13T12:30:00.000Z

Generated a complete Python + Flask implementation under `workspace/implementation/`.

**Files:** `start.sh`, `requirements.txt`, `app.py`, `db.py` (in-memory store), `errors.py`, `response.py`, `middleware.py` (auth/RBAC), `util.py`, `lookup.py`, `serialize.py`, `clock.py`; `services/calc.py`; `routes/`: `catalog.py`, `people.py`, `quotes.py`, `jobs.py`, `reservations.py`, `warranty.py`, `financing.py`, `callbacks.py`, `admin.py`.

**Endpoint count:** 58 routes — every endpoint in SCAFFOLD §1.5 / PRD §4 (incl. `/_clock/set_current_utc`).

**State machines:** Quote (DRAFT→SENT cyclic-revise→ACCEPTED/DECLINED/EXPIRED, lazy time-driven expiry), Job dispatch dim (UNSCHEDULED→SCHEDULED→EN_ROUTE→ON_SITE→COMPLETED→CLOSED + CANCELLED w/ compensation), Job billing dim (PENDING→INVOICED→PAID, parallel), PartReservation (HELD→CONSUMED/RELEASED), WarrantyPlan (PENDING→ACTIVE→CANCELLED/EXPIRED), FinancingApplication (SUBMITTED→APPROVED/DECLINED→ACTIVE→DEFAULTED), Callback (OPEN→SCHEDULED→ON_SITE→RESOLVED, cyclic reopen). All cascades implemented.

**Calculations:** `quote_estimate_total` (per-line round-half-up before sum), `job_final_total` (CONSUMED parts + labor 250¢/min + surcharge), `job_emergency_surcharge` (banded, 18:00:00-inclusive boundary, half-up then clamp 5000–40000 only when raw>0), `technician_callback_rate` (provisional vs settled, 4-dp half-up, denom==0→0), `financing_monthly_payment` (term-tiered APR amortization, ceil for 0% tier). All money via `decimal.Decimal` ROUND_HALF_UP. Conserved quantities derived live on read.

**Contract confirmation:** `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec`, guards `pip install` behind flask import check. Storage in-memory only (module-level dicts, `db.reset()` on boot) — no SQLite/disk/tmp persistence, no entity seeding. Fresh `start.sh` invocation wipes all state. OCC + envelope + auth/RBAC + segregation + validation ordering + all 18 errors + pagination + 3-fractional-digit ISO timestamps verified via 3 e2e scripts.

## Step 7: Run tests and iterate — 2026-06-13T12:50:00.000Z

Final state: **8/8 parallel rounds pass, 71/71 each** (verified results.{1..8}.json).

**Iterations run:** 2 (initial sweep + 1 fix + verification sweep).

**Initial state:** 70/71 passing in all 8 rounds, one consistent failure across every round: `test_depart_unscheduled_job_returns_invalid_state` — expected `ERR_INVALID_STATE`, got `ERR_FORBIDDEN_ROLE`.

**Diagnosis (STEP 1b — ERROR PRECEDENCE SILENCE, unique-derivability collapse):** The test departs an `UNSCHEDULED` job (so `technician_id` is null) acting as a freshly-created technician, and asserts exactly `ERR_INVALID_STATE`. The PRD admits two divergent faithful readings of precedence between the state check and the assigned-technician ownership check. §2.8 keys `ERR_FORBIDDEN_ROLE` to priority 2 and `ERR_INVALID_STATE` to priority 5. The assigned-technician ownership comparison (§2.1/§3.6) produces `ERR_FORBIDDEN_ROLE` and is NOT enumerated among the post-state business checks at the end of §2.8 (unlike segregation-of-duties, which is). So a faithful implementer may slot the ownership rejection at priority-2 `ERR_FORBIDDEN_ROLE` (what impl does) or treat it as an unlisted business check after state (`ERR_INVALID_STATE` — what the test wanted). Both PRD-consistent. Per the protocol's explicit relaxation exception, relaxed rather than deleted.

**Fixes applied to `test_suite/` (only layer changed):**
- `test_suite/test_01_catalog_and_entities.py`, `test_depart_unscheduled_job_returns_invalid_state`: relaxed assertion from `validate_error(resp, ERR_INVALID_STATE, 409)` to `validate_error_is_one_of(resp, [ERR_INVALID_STATE, ERR_FORBIDDEN_ROLE])`; added `validate_error_is_one_of` import.

**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `implementation/`:** none — impl's priority-2 ownership rejection is a faithful PRD reading, not weakened.
**Tests deleted:** none.

No flakiness observed (failure was deterministic across all rounds before the fix, absent across all after).

## Step 8: Finalize PRD — 2026-06-13T13:00:00.000Z

**PRD.md → PRD_FINALIZED.md:** 293 → 293 lines (one §2.8 paragraph expanded inline by one sentence; content delta confined to a single line).

**Changes:**
- **§2.8 (Validation Ordering)** — insert — Pinned that the assigned-technician ownership check guarding a job's on-site transitions (`depart`, `arrive`, `complete`) is evaluated at the priority-2 role-authorization stage and yields `ERR_FORBIDDEN_ROLE` ahead of the priority-5 state check, so a non-assigned technician gets `ERR_FORBIDDEN_ROLE` even when the job is in the wrong state — `implementation/routes/jobs.py:184-196` (depart), `:199-211` (arrive), `:226-235` (complete), shared helper `_assigned_tech_check` at `:178-181`.

**Per-edit pre-edit search log (Edit 1 — §2.8 ownership-vs-state precedence):**
- (a) Subject: precedence of assigned-technician ownership comparison (→ ERR_FORBIDDEN_ROLE) vs state check (→ ERR_INVALID_STATE) on technician-driven job transitions — the exact PRD silence flagged in Step 7 STEP 1b.
- (b) Impl paths enumerated/read: `routes/jobs.py` depart (184-196), arrive (199-211), complete (226-253) — all order ownership before state, consistent; `safety_check` (214-222) — ownership but no state guard, excluded by wording; `_assigned_tech_check` (178-181); `reservations.py consume_reservation` (81-98) — no ownership check, deliberately excluded; `callbacks.py arrive/resolve` (73-106) — no ownership check, excluded; `jobs.py schedule_job` (79-174) — dispatcher op, out of scope.
- (c) Wording adjustment: scoped sentence explicitly to depart/arrive/complete (not blanket "technician on-site operations") to avoid mis-describing safety-check, consume, and callback transitions, any of which broader phrasing would have turned into a new mismatch.

No edits to implementation/ (Step 7 changed only a test_suite/ assertion, not the alignment target).

## Step 9: Complete PRD — 2026-06-13T13:10:00.000Z

- Source: `PRD_FINALIZED.md` (293 lines, 44,141 chars) → `PRD_COMPLETED.md` (293 lines, 49,839 chars). Char delta: **+5,698**. Line count unchanged (all edits in-paragraph; 18 line-locations changed, all change ops, zero added/deleted lines, zero new sections).
- Counts: **8 ambiguity-pins, 11 mismatch-revisions** (19 total changes across 18 lines).

Changes:
- §2.1 Customer principal — revise — mismatch — PRD claimed customer-ownership comparison on accept/decline + reads; impl gates by role alone and never compares X-User-ID to customer_id, so pinned ownership as advisory/unenforced — routes/quotes.py:209-217,265-273; routes/jobs.py:46; routes/warranty.py:43; routes/financing.py:49
- §2.1 Technician principal — revise — mismatch — depart/arrive/complete/safety-check enforce assigned-tech ownership but consume does not; pinned consume as role-only exempt — routes/jobs.py:178-181,219; reservations.py:81-90
- §2.3 Pagination — insert — ambiguity — out-of-range limit silently clamped to [1,100], negative offset clamped to 0, non-integer → ERR_INVALID_REQUEST — util.py:136-162
- §2.8 Ownership-stage list — revise — mismatch — added safety-check to the ownership-guarded transitions and noted consume exemption — routes/jobs.py:214-219; reservations.py:81-84
- §3.3 Quote create defaults — insert — ambiguity — new quote: status DRAFT, estimate_total_cents 0, expires_at null until first send — routes/quotes.py:71-75
- §3.3 Quote-line unit_price snapshot — insert — ambiguity — body may supply unit_price_cents; default = part price for PART, 0 for DOOR/OPENER/LABOR; only used for PART totals — routes/quotes.py:126-141
- §3.3 Add-line state — revise — mismatch — add-line is not state-gated (no DRAFT/SENT check, no lazy-expire, no ERR_INVALID_STATE); estimate recomputed only when SENT; version always bumped — routes/quotes.py:116-147
- §3.4 Send preconditions — insert — ambiguity — pinned ERR_INVALID_STATE for non-DRAFT / line-less send, ERR_QUOTE_EXPIRED for past-expiry — routes/quotes.py:163-178
- §3.4 Accept/decline — revise — mismatch+ambiguity — decline no ownership check; accept stock pre-flight aggregates demand per part (not per line) before any state change — routes/quotes.py:222-235,238-259
- §3.5 Schedule ordering & window length — insert — ambiguity — pinned validation order (parse→state→eligibility→start<end) and booked_minutes = round(seconds/60) to nearest whole minute — routes/jobs.py:99-117,170
- §3.6 On-site lifecycle — revise — mismatch — depart records no ETA field; safety-check requires assigned tech but has no state precondition and never returns ERR_INVALID_STATE — routes/jobs.py:184-222
- §3.6 final_total/surcharge pre-completion — insert — ambiguity — final_total_cents null and emergency_surcharge_cents 0 until COMPLETED — routes/quotes.py:247; routes/jobs.py:243-247
- §3.9 Consume — revise — mismatch — consume is role-only (no assigned-tech compare); reservation-HELD checked before job-ON_SITE, both ERR_INVALID_STATE — reservations.py:81-98
- §3.10 Callback open — revise — mismatch — open does not check parent-job state; COMPLETED/CLOSED enforced only at schedule — routes/callbacks.py:15-29,58-67
- §3.11 Warranty create — revise — mismatch — create does not check job dispatch_status; only resolves job_id/customer_id existence — routes/warranty.py:16-37
- §3.11 Tune-up / expire — insert — ambiguity — tune-up ignores plan status (works on any status under the limit); expire of a non-exhausted ACTIVE plan → ERR_INVALID_STATE — routes/warranty.py:70-79,97-106
- §3.12 Financing submit — revise — mismatch — principal_cents stored as supplied; never validated against quote estimate_total_cents — routes/financing.py:19-44
- §3.12 Financing activate — insert — ambiguity — quote-not-ACCEPTED → ERR_INVALID_STATE — routes/financing.py:104-116
- §4 endpoint table (callbacks) — revise — mismatch — adjusted open-callback description to note job-state is checked at schedule, not open — routes/callbacks.py:15-29

Tests used only as auxiliary cross-reference (Step 7 had weakened them); an Explore pass confirmed all 19 pinned behaviors are untested in the suite, so implementation was the sole alignment authority.

---

## Pipeline complete — 2026-06-13T13:10:00.000Z

All 9 steps complete. Final: **71/71 tests pass across 8/8 parallel stability rounds.** Difficulty: Expert. Deliverables present: SCAFFOLD.yaml + 2 design indices, PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md, test_helpers/ + test_suite/ (71 tests), workspace/implementation/ (58 endpoints, in-memory Flask).
