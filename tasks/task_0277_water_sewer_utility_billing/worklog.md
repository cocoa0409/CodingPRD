# Worklog — task_0277_water_sewer_utility_billing

## Step 1: Create task directory — 2026-06-10T02:52:34.000Z

Created `tasks/task_0277_water_sewer_utility_billing/` and `tasks/task_0277_water_sewer_utility_billing/workspace/`. Pre-assigned output folder used directly (no tasks/ scan). Confirmed `./INSTRUCTION.md` exists for Step 3 copy.

## Step 2: Generate scaffold (Expert band) — 2026-06-10T03:10:00.000Z

The scenario text is preserved verbatim (only wrapped across lines via the YAML block scalar; the content is identical).

All three files are complete, lint-clean, and self-consistent. Here is the final summary.

### Summary

All three scaffold artifacts were written and pass `scaffold_lint.py` with **`VERDICT: clean lint`**.

**Design profile (Expert band):** pricing_engine × ledger_reconciliation; flat entity topology; parallel state-machine shape (Account carries two independent axes); peer_roles; immediate consistency. Complexity layers: dual-variant calculation, rate/threshold triggers, cascading side effects, derived-field reconciliation, optimistic concurrency.

**SCAFFOLD.yaml counts:**
- **Entities: 12** — RateSchedule, Account, Meter, MeterRead, BillingCycle, Bill, BudgetBillingPlan, AssistanceEnrollment, LeakAdjustment, ShutoffOrder, Payment, Moratorium
- **State machines: 5** — `Account.billing_status` (CURRENT/PAST_DUE/SHUTOFF_PENDING/DELINQUENT_PROTECTED), `Account.service_status` (ACTIVE/SUSPENDED/RESTORED) — parallel axes; `Bill.status` (branching DRAFT→POSTED→PAID + VOID); `LeakAdjustment.status` (branching adjudication); `ShutoffOrder.status` (cyclic SCHEDULED→EXECUTED→RECONNECTED) + 1 concurrency rule (OCC supersede on Account.version)
- **Calculation rules: 5** — tiered marginal water volumetric, sewer volumetric (uncapped vs winter-capped variants, irrigation excluded), leak credit, account balance reconciliation, budget-billing estimate-vs-chronological-trueup (forward/chronological variants)
- **Validation rules: 16** (priority-ordered, auth → existence → state → OCC → business safety/temporal/referential/fiscal)
- **Endpoints: 40** (39 business + 1 `/_clock/set_current_utc` test-driving; includes all FK reverse-reachability GETs)
- **Error catalog: 20**
- **Roles: 4** — BillingClerk, FieldOps, AssistanceCaseworker (opaque); Customer (entity_backed:Account)

**Design instance counts:**
- **§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml: 18 instances** — all 9 Difficulty Rules, 2 instances each, every rule's differentiation clause honored (different entity domains / error-category pairs / interval semantics / conserved quantities)
- **§1.9 SCAFFOLD_CORNER_DESIGN.yaml: 31 instances** (29 active + 2 `excluded_because:` stubs) across all 9 claim-extraction sections; both stubs reference resolvable §1.8 instances

**Verification performed:** all formula-derived assert literals computed in Python; 49 instance names confirmed unique across both files; no forbidden concurrency vocabulary; OCC endpoint contract satisfied; all FK descriptions use canonical `FK -> {Entity}.id` prefix; no design keys leaked into SCAFFOLD.yaml.

Files: SCAFFOLD.yaml (1045 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1258 lines), SCAFFOLD_CORNER_DESIGN.yaml (1152 lines).

## Step 3: Copy shared files — 2026-06-10T03:10:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0277_water_sewer_utility_billing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-10T03:15:30.000Z

**PRD.md written** — 280 lines / 43093 bytes.

**Withheld files confirmation:** Did NOT read either `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, and did not look at any sibling task. Generated purely from this task's `SCAFFOLD.yaml` plus the doc-generator skill spec.

**Major sections produced:**
- §1 Introduction — dual-axis account framing, deterministic billing, four-role overview
- §2 Global Specifications — RBAC, API Response Structure (verbatim), Pagination, Common Resource Properties & Two Status Axes, Derived Ledger Reconciliation, Monetary Precision & Rounding, OCC on budget-plan enrollment, Nested Resolution & Existence Ordering, Validation Ordering
- §3 Business Logic — 11 subsections: rate schedules, accounts/meters/reads, billing cycles & closure, bill generation charge stack, posting/voiding, payments & waterfall, budget billing & true-up, leak adjustments, arrears/shutoff/reconnect, assistance enrollment, moratoriums & server clock
- §4 Endpoint Definitions — 40 endpoints
- §5 Error Code Catalogue — 20 error codes

**Hard Contracts:** Contract 1 (field-name coverage) PASS (69/69 fields, one repair: meter_id added to §3.2); Contract 2 (rule coverage) PASS; Contract 3 (path purity §3) PASS. §2.2 verbatim block confirmed unmodified.

## Step 5: Generate unit tests — 2026-06-10T03:31:00.000Z

Generated complete test infrastructure from the four input files plus the unit-test-generator skill spec.

**`test_helpers/`** (9 files): `__init__.py`, `types.py` (entity TypedDicts + status/role enums; append-only `MeterRead`/`Payment` omit `updated_at`/`version`), `api_client.py`, `api_errors.py` (20-error catalog), `assertions.py` (per-entity + ledger-floor invariants), `factories.py`, `constants.py` (canonical rate schedule + pre-computed charge values), `test_users.py` (opaque-role constants + `make_customer_headers`), `fixtures.py` (composite tiered setups).

**`test_suite/`** (7 files): `conftest.py` + 6 domain files (`test_01_pricing`, `test_02_budget_billing`, `test_03_collections_workflows`, `test_04_shutoff_guards`, `test_05_lifecycle_errors`, `test_06_access_and_resources`).

**Coverage: 63 test functions, all PRD-cited and Design-tagged.**
- **Queue A (Difficulty):** 18 instances. **17 translated** (2 tests each = 34). **1 skipped**: `cross_entity_state_dependency/payment_does_not_restore_when_shutoff_already_executed` — setup internally inconsistent (14154 payment against 18980 bill cannot yield `Bill.status==PAID` and `past_due_cents==0`), asserted outcome not PRD-derivable/reachable; gap, not weakened.
- **Queue B (Corner):** 29 non-stub instances, **all 29 translated** (≥1 test each). 2 `excluded_because:` stubs not translated (cross-refs resolve to difficulty instances).
- Moratorium-vs-arrears precedence uses `validate_error_is_one_of([...])` (error-precedence Silence pattern); state-vs-arrears asserts `ERR_INVALID_STATE` directly (PRD §2.9 orders state legality before business rules).

**Verification:** all modules compile/import; pytest collects all 63 with zero errors; 79 distinctive (≥8-word) citations verbatim-match PRD.md; every test has exactly one resolving `Design:` line; all literal expected values independently recomputed; no scaffold leakage.

## Step 6: Generate implementation — 2026-06-10T03:31:00.000Z

Built complete Python + Flask implementation in `workspace/implementation/`.

**Files (27):** `start.sh` (executable, foreground, guarded pip install), `requirements.txt` (Flask only); core: `app.py`, `db.py`, `errors.py`, `response.py` (§2.2 envelope), `middleware.py` (auth/RBAC/ownership), `clock.py`; `routes/` (12 blueprints); `services/` (`common.py`, `calc.py`, `ledger.py`, `billing.py`, `lookup.py`).

**Endpoints:** 40 handlers covering all 40 PRD §4 rows (incl. `_clock` test hook).

**Storage/reset:** in-memory dicts keyed by id; `db.reset()` at module import on every process start; **no seeding** (fresh boot returns `[]`/`total_count: 0`). Per-test-server isolation gets a clean store each `start.sh` launch.

**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, `exec python3 app.py` foreground, guards pip behind `import flask` check. Booted HTTP-responsive within ~1s.

**PRD-fidelity:** marginal tiered water (sum-then-round once), sewer-ratio + optional winter cap, irrigation excluded from sewer, assistance fixed-charge discount, leak credit at lowest tier capped at water charge (Decimal ROUND_HALF_UP); two independent Account axes; derived ledger reconciliation + true-up; budget-billing flat installment vs chronological true-up; payment oldest-first waterfall + shutoff-cancel cascade; shutoff/execute/reconnect/cancel guards; OCC on budget-plan enrollment (412); full validation precedence.

## Step 7: Run tests and iterate — 2026-06-10T03:42:00.000Z

**Iterations run:** 1 diagnostic iteration, then 2 confirmatory 8-round parallel sweeps. Final state: all 16 rounds (2 sweeps × 8) passed 63/63.

**Initial state:** The first 8-round sweep showed all rounds dying at boot ("Server process exited prematurely with code -15") — a load artifact of 8 concurrent rounds each rebooting the Flask server before every test. A single isolated round revealed 60/63 with 3 distinct issues.

**Tests deleted:** None. All failures were a test bug or environmental flakiness, not PRD-silence.

**Fixes applied to `test_helpers/`:**
- `fixtures.py` — added new fixture `setup_protected_past_due_account`. It enrolls a shutoff-protection assistance enrollment *while the account is still CURRENT* (before cycle close), then closes the cycle to flip CURRENT→PAST_DUE. This leaves the account genuinely `PAST_DUE` with an `ACTIVE` protection enrollment — the only state from which the §3.9 `ERR_SHUTOFF_PROTECTED` guard is reachable.

**Fix applied to `test_suite/`:**
- `test_04_shutoff_guards.py::test_shutoff_protected_when_assistance_grants_protection` — switched to the new fixture. The old setup enrolled protection on an already-PAST_DUE account, which per PRD §3.10 transitions billing_status to `DELINQUENT_PROTECTED`; scheduling a shutoff from that state is an undefined transition that correctly yields `ERR_INVALID_STATE` (higher precedence than business-rule guards per §2.9), masking the protection check. TEST BUG (STEP 2): implementation precedence is PRD-faithful; protection guard reachable only from `PAST_DUE`, so the fixture was corrected, not the implementation.

**Fixes applied to `implementation/`:**
- `start.sh` — replaced the per-reboot `python3 -c "import flask"` subprocess check with a `.deps_ok` sentinel-file guard. The dependency check now runs once per workspace instead of spawning a full extra Python interpreter on every (8 rounds × 63 tests) reboot. Eliminated the boot-time contention causing code‑15 startup failures under the concurrent sweep (single-round wall time ~52s→38s). No entity data seeded; storage remains in-memory only; sentinel is a pure deps-presence marker.

**Orchestrator confirmation sweep:** Step 7 subagent's final sweep did not leave `results.{1..8}.json` on disk, so the orchestrator re-ran a fresh 8-round parallel sweep — all 8 rounds passed **63/63, 0 failed**. Durable results files now present in `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-06-10T03:47:00.000Z

**Result: ZERO edits warranted.** `PRD_FINALIZED.md` is a verbatim copy of `PRD.md` (280 lines each, 0% delta, `diff` confirms identical).

All three `<step_7_diff>` items are test-layer or launcher changes; none reveals a PRD silence or PRD/impl mismatch. The PRD already uniquely determines every behavior the Step 7 fixes touch.

- **`start.sh` `.deps_ok` sentinel (impl fix):** Pure launcher/perf change, no behavioral surface in PRD. No edit.
- **`setup_protected_past_due_account` fixture (test_helpers fix):** Pure fixture bug. PRD §3.10 already pins `DELINQUENT_PROTECTED` fires only when protection granted AND account `PAST_DUE`; §3.9 pins scheduling defined out of `PAST_DUE` (→ `ERR_INVALID_STATE`) and the `ERR_SHUTOFF_PROTECTED` guard. No edit.
- **`test_04::test_shutoff_protected...` fixture switch (test_suite fix):** Concerns §2.9 precedence (state legality before business rules) — already pinned verbatim in §2.9. No edit.

**Pre-edit NO-NEW-MISMATCH search (applied even with no edit):** enumerated `routes/assistance.py:38-39,75-76`, `routes/shutoff_orders.py:19-24,40-41,45-50,47-48`; all consistent with existing §3.9/§3.10/§2.9 prose. Intra-business-rule order (moratorium→protection→arrears) deliberately left open by PRD and not in Step 7 scope. No wording change.

`PRD_FINALIZED.md` confirmed verbatim copy of `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-10T03:51:30.000Z

Full PRD-vs-`implementation/` scan starting from `PRD_FINALIZED.md`.

**File:** `workspace/PRD_COMPLETED.md` — 280 lines, 43,980 chars (source 280 lines / 43,093 chars; char delta **+887**).

**Counts:** 4 ambiguity-pins, 1 mismatch-revision (5 edited lines; one §3.2 line carries two ambiguity-pins).

**Changes:**
- §3.2 Meters/Reads — insert — ambiguity — pinned `last_reading_gallons` = `reading_gallons` of the read with the latest `read_date` (chronological, not last-imported); read-list ordering = `read_date` ascending; `MANUAL` sub-prior read accepted with `consumption_gallons` clamped to zero — `routes/meters.py:25-30,142-143,105-116`
- §3.3 Cycle close — revise — ambiguity — "unpaid principal" = bill's full `total_cents` (no subtraction of partial payments); `late_fee_cents` assigned outright (not accumulated) — `routes/billing_cycles.py:60-63`
- §3.6 Payment posture — revise — mismatch — PRD said `billing_status` returns to `CURRENT` unconditionally when `past_due_cents` hits zero; impl only transitions from `PAST_DUE`/`SHUTOFF_PENDING` and never moves `DELINQUENT_PROTECTED` — `routes/payments.py:54-70`
- §3.9 Shutoff execute — insert — ambiguity — pinned two unnamed guard errors as `ERR_INVALID_STATE` (non-`SCHEDULED` order; non-`ACTIVE` service); made not-due-before-moratorium check order explicit — `routes/shutoff_orders.py:106-123`
- §3.9 Shutoff cancel — revise — ambiguity — pinned undefined-transition rejection as `ERR_INVALID_STATE`; fallback fires only when no other `SCHEDULED`/`EXECUTED` order remains and account is `SHUTOFF_PENDING` — `routes/shutoff_orders.py:161-176`

**Deliberate non-changes:** per-endpoint state-transition errors already pinned by global §2.9 ordering; chronological true-up, `applied_to_bill_id`, `anchor_balance_cents`, moratorium `active` derivation, clock endpoint empty-data 200 all already match impl. Tests used only as auxiliary cross-reference.

---

## Pipeline complete — 2026-06-10T03:51:30.000Z

All 9 steps finished. Final state: **63/63 tests pass across 8 parallel stability rounds.** Task artifacts present: SCAFFOLD.yaml (+ DIFFICULTY/CORNER design indices), worklog.md, test_helpers/ (9 files), test_suite/ (7 files), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md (verbatim copy), PRD_COMPLETED.md (5 ambiguity/mismatch pins), implementation/ (27 files + results.1..8.json all green)}.
