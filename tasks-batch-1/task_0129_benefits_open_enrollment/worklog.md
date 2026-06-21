# Worklog — task_0129_benefits_open_enrollment

## Step 1: Create task directory — 2026-06-03T17:37:23.000Z

Created `tasks/task_0129_benefits_open_enrollment/` with `workspace/` subdirectory. Pre-allocated index (no scan).

## Step 2: Generate scaffold (Expert difficulty) — 2026-06-03T17:57:51.000Z

Generated all three scaffold artifacts for **task_0129_benefits_open_enrollment** at **Expert** difficulty. All files written to `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0129_benefits_open_enrollment/`:
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Lint result:** `VERDICT: clean lint` — 346 §1.8/§1.9 calls all conform to §1.5, and all 14 §1.1 FKs have reverse-reachability GETs.

**Scaffold counts:**
- **Entities: 11** — Employee, WaitingPeriod, PlanOffering, PlanTier, Dependent, Enrollment, LifeEvent, EOIRequest, DeductionLine (immutable ledger), CarrierFeedRecord (immutable EDI), Form1095C
- **State machines: 8** — Employee, WaitingPeriod, Dependent (cyclic PENDING↔INFO_REQUESTED), Enrollment (branching w/ EOI + supersede + revert), LifeEvent (fork-join), EOIRequest, Form1095C, PlanOffering
- **Calculations: 5** — compute_monthly_employee_cost, compute_per_paycheck_deduction, compute_retro_deduction_delta (dual-variant prospective/retroactive), reconcile_carrier_premium (rounding-order pinned), compute_aca_affordability
- **Validations: 14** (priority-ordered)
- **Endpoints: 45** — above the Expert band (20–32); the overage is FK-reverse-reachability GETs (detail + filtered-list per entity) plus 2 test-driving endpoints (`/_clock/advance`, `/_payroll/run`), per the accepted FK-driven overage pattern
- **Errors: 16**
- **Roles: 4** (segregation_of_duties model) — BenefitsAdmin, DependentVerifier, PayrollOfficer, ComplianceOfficer (all `opaque` identity)
- **Concurrency rules: 2** — both OCC on `Employee.version` (life-event approve, enrollment activate)

**Design decisions:** compliance/audit + event-sourcing archetype, flat topology, branching state shape, segregation_of_duties RBAC. `api_prefix: ""`. All 9 Difficulty Rules satisfied with 2 instances each (18 §1.8 instances); §1.9 has 29 active corner tests + 10 `excluded_because` stubs. All formula-derived assertions pre-computed as literals (per-paycheck 8308 biweekly / 9000 semi-monthly; retro delta 27000 total; carrier reconcile 30967 round-per-line; voluntary-life 5000/7500; ACA threshold 9020 @ 100000 AFFORDABLE, 8930 @ 99000 UNAFFORDABLE). Added PlanOffering archive transition + ERR_PLAN_ARCHIVED to close a dead-end ARCHIVED enum.

## Step 3: Copy INSTRUCTION.md — 2026-06-03T17:58:09.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-03T18:03:01.000Z

Generated `workspace/PRD.md` (267 lines) from SCAFFOLD.yaml. Withheld design files NOT opened.

**Document metrics:** 5 top-level sections (1. Introduction, 2. Global Specifications, 3. Business Logic & Workflows, 4. Endpoint Definitions, 5. Error Code Catalogue), 20 subsections (10 under §2, 10 under §3). §2.2 emitted verbatim from section-2.2-response-structure.md.

**Hard Contract results:** Contract 1 (Field-Name Coverage) PASS — 62/62 required fields present, 0 missing. Contract 2 (Rule Coverage) PASS — all 8 state machines, 16 validations/priority chain, 2 OCC concurrency rules (framed as stale-version only), 5 calculations with pinned rounding order, cross-entity cascades expressed. Contract 3 (§3 Path Purity) PASS — 348 backtick tokens in §3, 0 paths/methods leaked.

Every scaffold entity (11), state machine (8), calculation (5), error (16), endpoint (45), and role (4) covered in prose. All enum/state values verbatim; HTTP contract confined to §4 table + §5 error table.

## Step 5: Generate unit tests — 2026-06-03T18:18:39.000Z

**test_helpers/ (9 files):** `__init__.py`, `types.py` (20 enums + 11 entity TypedDicts; DeductionLine & CarrierFeedRecord carry only id/created_at — immutable ledgers), `api_client.py` (all 45 endpoints), `api_errors.py` (16 errors + HTTP status map), `assertions.py`, `factories.py`, `constants.py` (pay-period counts, ACA 0.0902, LE window, VL unit size), `test_users.py` (opaque shared role headers), `fixtures.py` (composite setups).

**test_suite/ (8 test files + conftest, 65 test functions):** organized by domain — cost calculations, life-events/deductions, state machines, termination/eligibility, overlaps/priorities, ACA/invariants, CRUD/catalog, RBAC/security.

**Coverage (verified programmatically):** All 18 Difficulty instances ≥2 tests each (36 difficulty-tagged); all 29 non-stub Corner instances ≥1 test each (29 corner-tagged). Every test carries exactly one verbatim `Design:` tag resolving to a real instance — no orphan/dual/untagged. All 79 PRD citations verified verbatim. No skip/skipif/xfail.

**Instances skipped: 0** — every Difficulty and Corner non-stub instance had verbatim PRD coverage with unique derivability (PRD §2.10 pins validation precedence, §3.5–3.8 pin rounding orders, §3.6 pins cascade). 10 `excluded_because` Corner stubs correctly not emitted.

## Step 6: Generate implementation — 2026-06-03T18:18:39.000Z

Generated complete Python + Flask implementation in `workspace/implementation/`.

**Files:** `start.sh` (foreground, reads $PORT, binds 0.0.0.0, pip-install guarded by `import flask` sentinel), `requirements.txt` (flask==3.0.3), `app.py` (blueprints, error handlers, bind-retry loop), `clock.py` (logical UTC clock pinnable via /_clock/advance), `db.py` (in-memory dict stores), `errors.py` (16 error-id constants), `response.py` (envelope), `middleware.py` (X-User-ID/X-User-Role auth + RBAC 4 roles), `services/common.py`, `services/domain.py` (5 calculations, carrier feed, deduction ledger, eligibility re-eval, supersede cascade), `routes/` (employees, catalog, dependents, enrollments, eoi, life_events, payroll, forms, clock_ctl).

**Endpoint count: 45** (full §1.5 / PRD §4 coverage).

**Verified by 63 live smoke checks:** monthly cost (employer share rounded before subtraction, half-up), per-paycheck (annualize-then-divide 24/26), VL units×rate, ACA affordability (0.0902, `<=` boundary), carrier proration (round-per-line-then-sum), all state machines + cascades, validation precedence (PRD §2.10) incl. 30-day window boundary + OCC 412, SoD, archived-plan rejection, unverified-dependent rejection, FILED-form immutability.

**Confirmations:** in-memory only (dicts wiped on boot), nothing seeded at startup (empty GET /employees → total_count 0), start.sh reads $PORT / binds 0.0.0.0 / foreground via exec / pip guarded.

## Step 7: Test & iterate to green — 2026-06-03T19:00:17.000Z

**Iterations run:** 2 fix-and-sweep iterations + 1 confirmation sweep (subagent), then orchestrator re-verification (see note). Final state: 65/65 tests passing in every round.

**Diagnosis (subagent):** Initial sweep showed two distinct failure classes (true union 12 failing tests):
1. Setup `HTTP 422: ERR_INVALID_REQUEST - monthly_premium_cents must be a positive integer` — VOLUNTARY_LIFE/EOI tests. Fixtures created VL plan tiers with `monthly_premium_cents=0`. PRD §3.2 states verbatim: "It records the total monthly premium … in `monthly_premium_cents` (a positive integer)". Implementation correctly rejects 0 (catalog.py:104-105) → TEST_HELPERS bug per STEP 2, not an implementation bug.
2. "API server … could not be restarted" — known same-port bind-race flake, 1-5 of 8 rounds.

**Tests deleted:** None. Every failing test was either a faithful test blocked by a fixture bug (class 1) or a harness-restart flake (class 2). No PRD-silence or unique-derivability collapse found.

**Fixes to test_helpers/:** `fixtures.py` — `setup_pending_eoi_enrollment`: VL tier `monthly_premium_cents` 0→1 (positive, per PRD §3.2). VL cost derives only from `rate_per_1000_monthly_cents` × units; no EOI test asserts a `monthly_premium_cents`-derived value → no assertion weakened.

**Fixes to test_suite/ (same PRD-precondition class, inline tiers):** `monthly_premium_cents` 0→1 for VOLUNTARY_LIFE tiers in `test_01_cost_calculations.py`, `test_03_state_machines.py`, `test_05_overlaps_and_priorities.py`, `test_08_rbac_and_security.py`. These assert only on `error_id` or rate-formula `monthly_employee_cost_cents` → setup made PRD-faithful without altering assertions.

**Fixes to implementation/:** `app.py` — replaced probe-only `_bind_with_retry` with `_run_with_bind_retry`, wrapping `app.run()` in a retry loop catching `OSError(EADDRINUSE)`. Old code only probed a throwaway socket then handed off to werkzeug, leaving a TOCTOU window where werkzeug's real bind could hit the not-yet-released same-port socket and the process died ("could not be restarted"). New loop re-attempts the actual listen bind with backoff; on success `app.run()` blocks forever (body runs at most once).

Keep-alive BadStatusLine flake (hint #1) symptom never observed → `api_client.py` left unchanged.

**Orchestrator re-verification note:** Step 7 subagent's per-iteration `rm -f` left no persisted results files on exit (known gotcha), so orchestrator re-ran the 8-round sweep to regenerate + verify. First re-run used `--start-command "bash start.sh"` (outer cd only) → all 65 tests ERRORed with "could not be restarted" in all 8 rounds (per-test restarts spawn from pytest rootdir, not the impl dir — the start-command cwd gotcha; NOT an impl bug). Re-ran with `--start-command "cd <impl> && bash start.sh"` → **65/65 passed in all 8 rounds**. results.{1..8}.json persisted and green.

## Step 8: Finalize PRD — 2026-06-03T19:02:26.000Z

**Zero edits made.** `PRD_FINALIZED.md` is a verbatim copy of `PRD.md` (267 lines each, 0% delta, `diff` reports IDENTICAL).

All three Step 7 fix classes are pure fixture/boot-robustness fixes — none reveal a PRD silence or PRD/impl mismatch (verified against implementation/):
1. **app.py `_run_with_bind_retry`** (app.py:100-126) — boot/launcher robustness (EADDRINUSE retry loop). No API surface, no PRD-visible behavior. No edit.
2. **monthly_premium_cents 0→1** (fixtures + 4 test files) — impl enforces `> 0` at routes/catalog.py:104-105; PRD §3.2 already pins verbatim "in `monthly_premium_cents` (a positive integer)". Pure fixture bug, not a PRD gap. No edit.
3. **api_client.py keep-alive** — never observed, unchanged. No edit.

NO-NEW-MISMATCH enumeration performed for candidate subject `monthly_premium_cents`: impl paths routes/catalog.py:86-135 (sole write/validation, `>0`), services/domain.py:48/:91/:102 (consumers, no re-validation) — all consistent with existing PRD §3.2 wording. No wording adjustment needed.

## Step 9: Complete PRD — 2026-06-03T19:09:16.000Z

Produced `PRD_COMPLETED.md` via full PRD-vs-implementation scan. Source `PRD_FINALIZED.md` (267 lines, 43,404 chars) → `PRD_COMPLETED.md` (267 lines, unchanged — all edits in-paragraph; +4,712 chars).

**Counts:** 11 changes — 10 ambiguity-pins, 1 mismatch-revision.

**Per-change:**
- §3.1 Onboarding — insert — ambiguity — waiting period created when clock ≥ end_date is born ELAPSED, immediately opens eligibility (non-SEASONAL WAITING→ELIGIBLE, version bumped) — routes/employees.py:139,151-156
- §3.2 Plan Catalog — revise — mismatch — PRD asserted "at most one tier per benefit type may carry is_lowest_cost_self_only"; impl enforces NO uniqueness, accepts flag as supplied, §3.10 picks first such MEDICAL tier in creation order; also pinned monthly_premium_cents strictly positive — routes/catalog.py:104-105,119-123, routes/forms.py:20-28
- §3.4 Underwriting/Activation — insert — ambiguity — submit-eoi on non-over-GI-VL draft → ERR_INVALID_STATE; returns updated enrollment — routes/enrollments.py:171,177-180,192
- §3.4 EOI decide — insert — ambiguity — decide returns the EOI request object (not enrollment), increments request's own version on DENIED, leaves owning employee's version unchanged both branches — routes/eoi.py:66-81
- §3.6 Life event submission — insert — ambiguity — requested_coverage_amount_cents sole optional (defaults 0); other four required — routes/life_events.py:37,47-51
- §3.6 Life event approval — insert — ambiguity — 30-day window one-sided/whole-day: fires only when clock-date minus event-date exceeds 30 days; same-day/future/≤30-past pass — routes/life_events.py:134-137
- §3.7 Payroll run — insert — ambiguity — bills current pay_periods_processed as zero-based index before advancing; posts per ACTIVE enrollment in creation order; allowed regardless of eligibility; nothing with no active enrollments; returns updated employee — routes/payroll.py:36-49
- §3.7 Retroactive variant — insert — ambiguity — processed periods = prior enrollment's existing REGULAR lines; billed coverage date = logical-clock date when line posted; each RETRO_ADJUSTMENT carries NEW enrollment's enrollment_id; no retro lines when no prior active enrollment — routes/life_events.py:190-216, services/domain.py:138,144-155
- §3.9 Detach dependent — insert — ambiguity — no verification/prior-attachment check, decrements unconditionally (may go below zero) — routes/enrollments.py:234-248
- §3.10 ACA generation — insert — ambiguity — tax_year required integer (else ERR_INVALID_REQUEST); benchmark tier in creation order if multiple; no benchmark → ERR_INVALID_REQUEST — routes/forms.py:37-47
- §4 Endpoint intro — insert — ambiguity — 201 vs 200 pinned (submit-eoi=200; _clock/advance=200 empty data); enumerated optional equality-filter query params per list endpoint (carrier-feed-records does NOT filter by employee_id); unrecognized params ignored — all list handlers + clock_ctl.py:29

No remaining PRD silence/mismatch for endpoints, state transitions, calculations, validation/error ordering (§2.10), envelopes, versioning, or ledger-immutability.

---

## Pipeline complete — 65/65 tests green across 8 parallel rounds. All artifacts present.
