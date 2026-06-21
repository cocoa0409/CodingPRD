# Worklog — task_0226_rent_to_own_home

Scenario: Rent-to-Own / Lease-Purchase Home: option fee & rent-credit accrual, lease + purchase-option term, payment split (rent/credit), maintenance responsibility, option exercise/expiration, purchase-price lock, default/forfeiture, conversion to mortgage

Difficulty: Expert

## Step 1: Create task directory — 2026-06-07T00:00:00.000Z

Created `tasks/task_0226_rent_to_own_home/` and `tasks/task_0226_rent_to_own_home/workspace/` directly (provided task_dir, skipped index scan to avoid ID contention with parallel tasks).

## Step 2: Generate scaffold (Expert) — 2026-06-07T00:00:00.000Z

All three scaffold artifacts are generated and verified. Here is the final report.

Generated all three Expert-level scaffold artifacts for `task_0226_rent_to_own_home/`, verified with a clean `scaffold_lint.py` run (373 calls scanned, zero violations).

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** Ledger-reconciliation primary archetype + Compliance/audit secondary; layers = dual-variant calc, optimistic concurrency, cascading side effects, rate/threshold triggers; flat topology; branching state-machine shape; peer roles; immediate consistency.

**Contents:**
- **Entities (8):** Landlord, Tenant, Property, Agreement, RentPayment, MaintenanceTicket, OptionExercise, Mortgage.
- **State machines (5):** Property (AVAILABLE↔UNDER_AGREEMENT→SOLD), Agreement (branching DRAFT→ACTIVE→{EXERCISED→CONVERTED, DEFAULTED, EXPIRED}), RentPayment (PENDING→PAID/LATE with LATE→PAID cure loop and →FORFEITED), MaintenanceTicket (OPEN→APPROVED→RESOLVED/REJECTED), OptionExercise (PENDING→SETTLED/VOIDED). 1 concurrency rule (OCC stale Property.version on activate, 412).
- **Calculations (6):** payment_split, rent_credit_accrual (dual-variant provisional vs final), maintenance_cost_split (dual-variant estimate vs actual), purchase_settlement (nested min/max + conditional), late_fee_assessment (grace boundary), mortgage_amortization.
- **Validations:** 14, priority-ordered (auth → authz → existence → request-validation → referential → OCC → state → temporal → safety → fiscal). OCC deliberately ordered at priority 6, before the property-availability/state checks, so the stale-version test is deterministic.
- **Endpoints:** 32 (CRUD + filtered-list reverse-reachability GETs for every FK + action endpoints + one `/_clock/set_current_utc` test-driving endpoint).
- **Error catalog:** 20 codes, all referenced by a validation or transition.
- **Roles (3):** Landlord (entity_backed), Tenant (entity_backed), EscrowAgent (opaque).

**Design instances:** §1.8 = 18 (all 9 difficulty rules × 2 instances). §1.9 = 39 (32 active recipes + 7 `excluded_because:` stubs, each pointing at an existing §1.8 instance by name).

**Key findings / fixes during generation:**
- `api_prefix` set to `/` (flat multi-collection topology) so the lint's collection-segment heuristic resolves every FK's filtered-list reverse-reachability GET.
- Reordered validations to put the OCC version check ahead of the property-availability check, and fixed the cross-entity/temporal-overlap recipes to capture the *Property's* fresh version via an inserted `GET /properties/{id}` (the activate response returns the Agreement's version, not the Property's) — without this the ERR_PROPERTY_NOT_AVAILABLE tests would have non-deterministically returned ERR_STALE_VERSION.
- All formula-derived asserts pinned to literals computed in code (e.g., net_due 29320000, cap-binding 750000, late_fee 10000, round-per-payment 10000/30000, splits 50000/70000). No forbidden concurrency vocabulary; no duplicate instance names.

## Step 3: Copy shared files — 2026-06-07T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-07T00:00:00.000Z

Generated `workspace/PRD.md` (254 lines) — a prose PRD for the Rent-To-Own Home API.

### Section structure
- **§1 Introduction** — ledger-reconciliation + compliance framing of lease-purchase economics.
- **§2 Global Specifications** (10 subsections): 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Money/Precision/round-then-sum, 2.6 Hierarchical Consistency & Cascading State, 2.7 OCC on Property Activation, 2.8 Validation Ordering / error-precedence ladder, 2.9 Nested Resource Retrieval, 2.10 Test-Driving Clock.
- **§3 Business Logic** (8 subsections by lifecycle): parties+property, drafting/activation, monthly payment scheduling + split, record/cure/forfeit, maintenance tickets, option exercise+settlement, mortgage conversion, default/expiry collapse.
- **§4** 32-endpoint table; **§5** 20-error table.

### Coverage
- Entities: all 8. Endpoints: all 32. Errors: all 20. State machines: all 5 (every transition + cascade). Calculations: all 6 (incl. dual-variant credit/maintenance, 5-step settlement, grace boundary, both amortization branches).

### Hard Contract reports: Field coverage PASS (51/51), Rule coverage PASS, Path purity PASS (§3 has 0 path tokens).

### Notable scattering choices
- OCC stated in §2.7 in pure stale-version terms (no race vocabulary), reinforced at §3.2; §2.8 ladder makes the 412 check precede availability/state checks.
- Provisional vs final credit (`gross_credit_accrued_cents` over PENDING/PAID/LATE vs `available_credit_cents` over PAID-only) in §3.3; accrual mutations scattered into §3.4 transitions.
- Round-then-sum in §2.5; per-period rounding unit re-anchored at §3.3.
- Default cascade (forfeit non-terminal payments, zero credit, release property, void pending exercise) and expiry cascade rendered with equal density in §3.8.
- Preserved verbatim: stale `expected_property_version` returns 412 even when property already `UNDER_AGREEMENT` (OCC ranks above availability check).

## Step 5: Generate unit tests — 2026-06-07T00:00:00.000Z

NOTE: First Step 5 subagent timed out (stream idle) after writing all test_helpers/ modules + conftest.py but before test_suite/. A fresh subagent (SendMessage unavailable) completed the suite, reusing the existing helpers unchanged and adding two composite fixtures.

Completed the PRD-benchmark unit test suite, building on the already-written `test_helpers/` and `conftest.py`.

### Test files generated — 4 files, 68 test functions
- `test_suite/test_01_agreement_lifecycle.py` (18 tests) — entity CRUD, defaults, system fields, DRAFT→ACTIVE with OCC, property occupancy/availability, version increment, duplicate-period.
- `test_suite/test_02_payments_and_credit.py` (17 tests) — payment split, provisional vs final accrual, per-payment rounding, record/cure/forfeit, grace boundary, conservation, side effects, list filter, invalid transitions, RBAC.
- `test_suite/test_03_maintenance.py` (9 tests) — estimate vs actual split, threshold boundary, conservation, reject/approve/resolve errors.
- `test_suite/test_04_option_exercise_and_mortgage.py` (24 tests) — settlement math, conversion cascade, default/expiry, credit-score gate, reference mismatch, error-precedence ladder, RBAC/auth.

### Coverage
- **Queue A (Difficulty):** all 18 instances translated, each with exactly 2 tests (36 tests). 0 skipped.
- **Queue B (Corner):** all 32 non-stub instances translated, 1 test each (32 tests). 0 skipped. The 7 `excluded_because:` stubs correctly NOT translated; all 7 difficulty cross-refs verified resolvable.
- Every test carries exactly one `Design:` tag (68 tags / 68 tests); all docstring PRD citations verbatim-grep-verified against `PRD.md`.

### test_helpers changes (minimal, additive)
- `test_helpers/fixtures.py` — added `setup_agreement_with_late_payment` (LATE-payment cure cycle) and `setup_two_drafts_on_one_property` (OCC stale-version / single-occupancy / cross-entity availability share this 4-call preamble). No corrections needed to existing helpers; all reused unchanged (`from .fixtures import *` auto-re-exports).

### Notable PRD-fidelity decisions
- Two version-numeric corner instances: PRD §2.4 says version "begins at its initial value" without pinning to 1 — so `entity_system_fields_generated` asserts 201 + `status==AVAILABLE` + bare-UUID id + ISO timestamps (dropping non-derivable `version==1`), and `ccl_version_increments_on_mutation` asserts relational `after==before+1` + `status==UNDER_AGREEMENT` rather than absolute `version==2`. Both stay uniquely derivable.
- Final checks: all files byte-compile; no scaffold/§1.x/test_recipe leakage; no skip/skipif/xfail markers.

## Step 6: Generate implementation — 2026-06-07T00:00:00.000Z

Built a complete Python + Flask implementation in `workspace/implementation/`. All endpoints, state machines, calculations, validations, and RBAC implemented and verified against four self-written smoke suites — all passing.

### File / module layout
- `start.sh` — foreground launcher (reads `$PORT`, default 10000; binds `0.0.0.0`; guards `pip install` on a cheap `import flask`; `exec python3 app.py`).
- `app.py` — Flask entry: blueprint registration, `ApiError`/404/405 handlers, per-request global-lock acquire/release (atomicity), `app.run(host=0.0.0.0, port=$PORT, threaded=True)`.
- `db.py` — in-memory store + logical clock. `errors.py` — error catalog (IDs→HTTP). `response.py` — exact envelope. `middleware.py` — X-User-ID/X-User-Role auth (3 roles verbatim). `validation.py` — body parsing/range checks (all → ERR_INVALID_REQUEST 422).
- `routes/` — one blueprint per group (parties, properties, agreements, rent_payments, maintenance, option_exercises, mortgages, clock + helpers.py). `services/` — `calc.py` (Decimal calcs) + `domain.py` (stamping, accrual recompute, cascades, add_months).

### Storage
Eight module-level dicts in `db.py` keyed by UUID, all empty at boot. No SQLite/JSON/seeding — every entity created via declared endpoints. Module re-import on relaunch wipes all state. Single `RLock` acquired in before_request / released in teardown_request for atomic transitions+cascades.

### Notable choices for harder rules
- **OCC**: `expected_property_version` checked on `/agreements/{id}/activate` strictly before state and property-availability checks (priority 6). Stale version → ERR_STALE_VERSION 412 even when property already UNDER_AGREEMENT; correct-version-but-non-DRAFT → ERR_INVALID_STATE; missing field → 422 (priority 4) before OCC. Only endpoint accepting a version field.
- **Dual-variant calcs**: maintenance split recomputes on estimate at approval, overrides with actual at resolution. Credit accrual carries gross (PENDING/PAID/LATE) and available (PAID-only). Purchase settlement follows pinned 5-step order (snapshot → cap → nested min → fee-credit branch → net).
- **Rounding**: all money via Decimal ROUND_HALF_UP; per-payment credit rounded first, then agreement sums already-rounded per-period values (round-then-sum). Late fee = round_half_up(amount*0.05). Mortgage amortization uses high-precision Decimal powers, rounds only final installment; zero-rate branch = round_half_up(P/n).
- **Cascades**: activation flips property AVAILABLE→UNDER_AGREEMENT; conversion →SOLD; default/expire →AVAILABLE — each bumps affected resource version+updated_at. Default also forfeits all non-terminal PENDING/LATE payments, voids any PENDING OptionExercise, forces available_credit_cents→0 via sticky `_credit_forfeited` flag.
- **Accruals recomputed from children on every read** (`serialize_agreement`); superseded rows excluded from accrual and uniqueness. Fixed a real bug: duplicate-period check excludes the row the incoming request supersedes, so re-billing a cured/forfeited period succeeds.
- Spec note: ERR_INVALID_REQUEST returns 422 per this PRD §5/scaffold (not the 400 generic template).

## Step 7: Run tests and iterate — 2026-06-07T00:00:00.000Z

**Iterations run:** 1 (the very first 8-round parallel sweep passed clean).

**Result:** All 8 parallel rounds passed with `passed == total == 68`, `failed == 0`, `errors == 0` in every round (orchestrator independently re-verified all 8 results.{1..8}.json: 68/68/0 each). No flakiness surfaced across the concurrent sweep — including timing-sensitive paths (OCC stale-version on activation, two-drafts-on-one-property occupancy race, per-test-server reboots under 8× concurrent load).

**Tests deleted:** None. Every test traces to verbatim PRD prose and is uniquely derivable.
**Fixes applied to `test_helpers/`:** None required.
**Fixes applied to `implementation/`:** None required.

The exit condition (all 8 rounds green) was met on the first sweep. Implementation and test suite were already mutually consistent and faithful to PRD.md — covering agreement lifecycle with OCC on property version, round-then-sum credit accrual (provisional `gross_credit_accrued_cents` vs finalized `available_credit_cents`), grace-day boundary + 5% late fee, maintenance threshold split, pinned settlement order on option exercise, amortized mortgage conversion, default/expiry collapses, and the full error-precedence ladder.

Process note: subagent's initial pass/fail parser keyed on a nonexistent `outcome` field (results JSON uses `status`); re-parse on the correct field confirmed the clean sweep — no code or test changed based on the bad parse.

**Step 8 decision:** Step 7 ended with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes — zero iterations beyond baseline. Per the skip condition, **Step 8 (PRD finalizer) is SKIPPED**; PRD.md already determined every behavior the implementation exhibits. PRD_FINALIZED.md will not be produced. Proceeding directly to Step 9.

## Step 8: Finalize PRD — SKIPPED — 2026-06-07T00:00:00.000Z

Skipped per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions / 0 test_suite fixes / 0 test_helpers fixes / 0 implementation fixes. No PRD_FINALIZED.md produced.

## Step 9: Complete PRD — 2026-06-07T00:00:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD.md` (PRD_FINALIZED.md did not exist).

**Counts**
- Source `PRD.md`: 254 lines, 37,480 chars
- `PRD_COMPLETED.md`: 254 lines, 39,312 chars (char delta +1,832; no line-count change — all edits in-paragraph)
- Changes: 9 total — 7 ambiguity-pins, 2 mismatch-revisions

**Changes**
- §2.2 (API Response Structure) — insert — ambiguity — pinned `total_count` (filtered count pre-pagination) and `has_more` formula (`offset + page_len < total_count`) — `response.py:42-48`
- §2.3 (Pagination) — insert — ambiguity — pinned non-integer/out-of-range `limit` (outside 1–100) and non-integer/negative `offset` → `ERR_INVALID_REQUEST` (422); `id` as tie-break within equal `created_at` — `routes/helpers.py:30-49,58`
- §2.4 (Common Resource Properties) — insert — ambiguity — pinned `version` initial value = `1` — `services/domain.py:25`
- §3.1 (Parties/Property) — revise — mismatch — PRD claimed landlord/tenant `email` and property `address` "must be unique"; impl enforces no uniqueness and has no such error code → revised to "expected to be unique, though the system does not reject a duplicate" — `routes/parties.py:16-63`, `routes/properties.py:16-41`
- §3.1 (Property) — insert — ambiguity — pinned `landlord_id` must resolve (`ERR_NOT_FOUND`) then equal acting `X-User-ID` (`ERR_FORBIDDEN`), in that order — `routes/properties.py:26-30`
- §3.2 (Agreement draft) — insert — ambiguity — pinned `option_deadline` calendar-month arithmetic with day-clamp-down for short target months — `services/domain.py:38-50`
- §3.3 (RentPayment scheduling) — insert — ambiguity — pinned supplied `supersedes_payment_id` must exist (`ERR_NOT_FOUND`); the pointed-to row is excluded from uniqueness/accrual; the new referencing row counts normally — `routes/rent_payments.py:36-49`, `services/domain.py:61-68`
- §3.4 (Forfeit) — revise — mismatch — PRD claimed forfeit returns `ERR_PAYMENT_NOT_LATE` for a non-late row; impl always returns `ERR_PAYMENT_NOT_PENDING` for any non-forfeitable (terminal `PAID`/`FORFEITED`) row, with row-state check before agreement-active check — `routes/rent_payments.py:175-184`
- §3.5 (MaintenanceTicket) — insert — ambiguity — pinned `actual_cost_cents`, `tenant_share_cents`, `landlord_share_cents` are `null` on a freshly opened ticket — `routes/maintenance.py:32-44`
- §3.7 (Mortgage conversion) — insert — ambiguity — pinned `option_exercise_id` must resolve (`ERR_NOT_FOUND`); wrong-agreement OR non-`SETTLED` exercise → `ERR_REFERENCE_MISMATCH` — `routes/mortgages.py:31-42`

**Notable findings**
- Most significant gap: uniqueness mismatch (§3.1) — PRD asserted hard uniqueness for landlord/tenant emails and property addresses, but impl performs no such check and the error catalogue has no corresponding code (also absent from test suite). Revised to match impl rather than invent an unimplemented constraint.
- Already-pinned behaviors left untouched: round-then-sum credit accrual, 5% late fee, maintenance threshold split, settlement order, amortization (both branches), OCC precedence on activation, default/expiry cascades, §2.8 error ladder.

---

## Pipeline complete — 2026-06-07T00:00:00.000Z

All 9 steps done. Final state: 68/68 tests pass across all 8 stability-sweep rounds. Artifacts: SCAFFOLD.yaml (+DIFFICULTY/CORNER design), workspace/PRD.md, workspace/PRD_COMPLETED.md (Step 8 skipped → no PRD_FINALIZED.md), test_helpers/, test_suite/ (4 files, 68 tests), workspace/implementation/ (Flask, in-memory). Difficulty: Expert.
