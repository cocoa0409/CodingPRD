# Worklog — task_0032_ira_rmd_management

## Step 1: Task directory verification — 2026-05-28T00:00:00Z

Pre-created task directory `tasks/task_0032_ira_rmd_management/workspace` verified. Skipped index scan and mkdir per user instruction.

## Step 2: Generate scaffold — 2026-05-28T00:00:00Z

Profile fits the Advanced/Expert band (10 entities, 42 endpoints, 14 errors, 5 state machines with cyclic and non-linear shapes, 6 calculations with 2 dual-variant calcs).

Final lint verdict:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Generated three scaffold artifacts for `task_0032_ira_rmd_management` strictly from the scenario description and the scaffold-generator skill spec, without consulting any sibling tasks.

**Files written:**
- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

**Design summary (SCAFFOLD.yaml §1.0–§1.7):**
- **Archetype**: compliance_audit (primary) + pricing_engine (secondary); layers: OCC, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation
- **Topology/shape**: hybrid topology, compound state machines, peer_roles (PlanAdministrator/AccountOwner/IRSAuditor)
- **10 entities** (AccountOwner, IRAAccount, BeneficiaryDesignation, Contribution, Conversion, Distribution, RMDSchedule, Form1099R, AuditEvent, SystemClock)
- **5 state machines** including non-linear shapes (IRAAccount branching, RMDSchedule cyclic OPEN→DELINQUENT→SATISFIED)
- **6 calculations** with **2 dual-variant calcs** (`backdoor_roth_pro_rata` single-vs-aggregated; `rmd_amount` living-vs-secure_10year)
- **13 validations** with priority ordering, **14 errors**, **42 endpoints**, **2 OCC concurrency rules**
- All FKs use the canonical `FK -> <Entity>.id` prefix; every FK has reverse-reachability GET in §1.5

**Difficulty design (§1.8)**: All **9 rules × 2 instances = 18 total**. Per-instance literals were pre-computed (e.g., taxable=150000/nontaxable=50000 for aggregated pro-rata at gross=200000, pre=600000, aft=200000; RMD required_amount_cents=26315 for age 73 / balance 700000 at divisor 26.60; phase-out yields headroom=450000 at AGI=16M SINGLE 2026). Each instance's `setup_api_calls` chain is fully bound — every `${var}` traces to a prior `captures:` block.

**Corner design (§1.9)**: 23 active instances + 2 `excluded_because:` stubs spanning sections entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model.

**Verification**: `scaffold_lint.py` reports:
```
Coverage
  §1.5 endpoints declared:    42
  §1.1 entities declared:     10
  §1.8 instances scanned:     18
  §1.9 instances scanned:     23
  Calls scanned (§1.8+§1.9):  333

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy INSTRUCTION.md — 2026-05-28T00:00:00Z

Copied `INSTRUCTION.md` from project root to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-28T00:00:00Z

The single "around" is in the §1 introduction sentence "rules around concurrency and rounding" — a non-quantitative discourse usage, not a fuzzy threshold. That's fine.

PRD generated at `workspace/PRD.md`.

**Hard Contract Reports**

```
Field coverage check:
- entities[].fields: 47 required, 47 present, 0 missing
- endpoints[].request_body: 26 required, 26 present, 0 missing
- endpoints[].query_params: 15 required, 15 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 13 checked, 13 expressed in prose (§2.6 priority sequence), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint, expected_account_version, ERR_STALE_VERSION/412 all named in §2.7), 0 missing
- state_machines[].transitions: 19 checked, 19 fully expressed across §3.2–§3.7, 0 missing
- calculations[]: 6 checked (contribution_limit, roth_eligibility with all 12 AGI brackets, backdoor_roth_pro_rata with single + aggregated variants, rmd_amount with Uniform Lifetime + SECURE variants, form_1099_r code mapping, distribution_basis_split), 6 fully expressed step-for-step in business prose, 0 missing
- validations[] conditions: 13 checked (auth/role/ownership/existence/state/OCC/kind-mismatch/tax-year/cap/balance/beneficiary-shares/SECURE/conversion-pair), 13 matchable to error_id in §2.6 and §3 narratives, 0 missing
- endpoints[].side_effects / applies_to: 23 endpoints with side-effects checked, 23 expressed in §3 workflow narratives, 0 missing
- entities[].fields[] structured content: 47 fields checked (types, defaults, enum constraints, append-only Form1099R/AuditEvent with no version/updated_at noted in §2.4), 47 reconstructible from prose, 0 missing
- sibling-branch symmetry: 5 groups checked (PRETAX/AFTERTAX/ROTH contribution kinds, single vs aggregated pro-rata, Uniform Lifetime vs SECURE pace, freeze/unfreeze symmetric, ACTIVE→CLOSED vs INHERITED→CLOSED), 5 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 501
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Structural summary**

- §2 has 10 subsections (2.1 RBAC, 2.2 verbatim envelope, 2.3 pagination, 2.4 identifiers/timestamps/versioning, 2.5 nested-resource path validation, 2.6 validation precedence, 2.7 OCC on confirms, 2.8 cascade consistency, 2.9 monetary precision, 2.10 explicit clock).
- §3 has 9 domain-derived subsections following a lifecycle/entity-grouping strategy: owner registration → account open/operate → contributions → distributions/1099-R → conversions → beneficiaries/death cascade → RMD schedules/year-rollover → audit stream → 1099-R artefact.
- §4 endpoint table: 4 columns (Method, Path, Description, Authorized Role(s)), 41 endpoints.
- §5 error table: 2 columns (Error ID, HTTP Status Code), 14 errors.
- §2.2 emitted byte-for-byte from `section-2.2-response-structure.md` (placeholder ids, timestamp, `"data": { }` all preserved).
- All 6 calculation formulas (`contribution_limit`, `roth_eligibility`, `backdoor_roth_pro_rata`, `rmd_amount`, `form_1099_r`, `distribution_basis_split`) translated into step-for-step prose with all constants embedded — no pseudocode, no fuzzy words, sum-then-divide/sum-then-floor ordering and final-step floor truncation explicit.

## Step 5: Generate unit tests — 2026-05-28T00:00:00Z

Generated complete Stage 1 (test_helpers/) and Stage 2 (test_suite/) for task_0032_ira_rmd_management.

**Stage 1 — `test_helpers/` (9 files, ~1591 lines):**
- `types.py` — entity TypedDicts (resource entities carry id/created_at/updated_at/version per PRD §2.4; Form1099R and AuditEvent declared with only id+created_at), 7 status enums, role/filing/relationship enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (37 methods covering owners, accounts, contributions, distributions, conversions, beneficiaries, RMD schedules, 1099-Rs, audit events, clock, year-rollover)
- `api_errors.py` — 14 error IDs from PRD §5 with HTTP status map; registers with framework
- `assertions.py` — per-entity field-level assertions + `assert_common_fields` / `assert_append_only_fields` discriminator
- `factories.py` — payload factories with PRD-exact field names
- `constants.py` — base/catch-up cents, Roth phase-out brackets, Uniform Lifetime divisor table (basis-point form), SECURE constants
- `test_users.py` — TEST_USERS dict + `make_account_owner_headers(owner_id)` for identity-threading (AccountOwner is the only entity-backed role per PRD §2.1)
- `fixtures.py` — Tier 0 clock, Tier 1 leaf creators, Tiers 2–7 contribution/distribution/conversion/beneficiary/RMD lifecycle helpers, Tier 8 composites (`setup_funded_traditional`, `setup_funded_traditional_with_open_rmd`, `setup_inherited_traditional_with_secure_deadline`)
- `__init__.py` — barrel export

**Stage 2 — `test_suite/` (11 files, 56 tests, ~2862 lines):**
- `conftest.py` — pytest fixture bridge
- `test_01–test_10` — claim-driven tests organized by domain (owner/account basics, auth, state machines, caps, conversions/pro-rata, RMD/distributions, priority + OCC, compensating invariants, listing/pagination, additional difficulty-instance coverage)

**Coverage (counts derived from `Design:` docstring lines):**
- Difficulty queue (A): every translated instance covered by ≥2 tests
- Corner queue (B): every translated non-stub instance covered by ≥1 test

**Instances skipped (PRD-first two-condition filter failed):**
- `Difficulty/priority_pair_validation_conflict/kind_mismatch_outranks_contribution_cap_on_contribution_create` — instance asserts ERR_KIND_ACCOUNT_MISMATCH at `POST /ira/contributions` (creation), but PRD §3.3 explicitly puts kind compatibility "At confirm time"; a PRD-only reader could correctly leave creation kind-agnostic, so the assertion isn't uniquely derivable.
- `Corner/rbac/irs_auditor_cannot_initiate_conversion` and `Corner/rbac/account_owner_cannot_run_ops_year_rollover` — both instances assert `ERR_INVALID_ROLE` (401), but per PRD §2.1 a recognized-but-unpermitted role yields `ERR_UNAUTHORIZED` (403). The asserted error_id isn't PRD-derivable.

**Stubs verified (not translated, no placeholder emitted):**
- `Corner/entities/form_1099_r_is_immutable_no_update_endpoint` → covered by `Difficulty/compensating_invariant/distribution_confirm_then_reverse_conserves_rmd_satisfaction`
- `Corner/consistency_model/immediate_consistency_balance_visible_in_same_response` → covered by `Difficulty/compensating_invariant/contribution_confirm_then_reverse_conserves_account_balance_and_ytd`

## Step 6: Generate implementation — 2026-05-28T00:00:00Z

**Location:** `workspace/implementation/`

**Stack:** Python + Flask (mandated by the skill). Single in-memory store, empty on every boot — no seeding.

**Files written:**
- `start.sh` (executable; `python3 -m pip install` then `exec python3 app.py`; binds `0.0.0.0:$PORT`, default 10000)
- `requirements.txt` (Flask 3.0.3)
- `app.py` — entry point, blueprint registration, error handlers (APIError → standard envelope, plus 404/405/HTTPException fallbacks)
- `db.py` — in-memory dicts (`owners`, `accounts`, `beneficiary_designations`, `contributions`, `conversions`, `distributions`, `rmd_schedules`, `forms_1099r`, `audit_events`) and the `SystemClock` singleton
- `errors.py` — `APIError` class + the 14 catalog entries from PRD §5
- `response.py` — success_object / success_array / error_response with the PRD §2.2 envelope (`meta`/`response_type`/`data`, `api_request_id` prefixed `req_`, ISO 8601 UTC with three fractional digits and trailing Z)
- `middleware.py` — `X-User-Role` and `X-User-ID` header parsing, role gating, owner-match check
- `serializers.py` — entity-to-JSON shapes with deterministic field sets
- `calculations.py` — `contribution_limit`, `roth_eligibility` (sum-then-floor to nearest 1000 cents), `backdoor_roth_pro_rata`, `distribution_basis_split`, `compute_taxable_distribution`, `map_distribution_code` (with the 59½ boundary), `rmd_required_amount` (sum sorted by `opened_at` ASC then `created_at` ASC, then `(total*100)//divisor_x100`), `rmd_deadline` (April 1 of year+1 for first-RMD year else Dec 31), `secure_inherited_required_amount`
- `helpers.py` — JSON-body parsers (int/str/enum/bool with `ERR_INVALID_REQUEST`), ISO 8601 parser, pagination (limit 1–100 default 10, offset default 0), `paginate` (sorts by `created_at` ASC), `append_audit_event`, `recompute_rmd_posture` (DELINQUENT > OPEN-with-shortfall > all-SATISFIED → REQUIRED_MET), `void_form_1099r_for_distribution`
- `routes/owners.py`, `routes/accounts.py`, `routes/contributions.py`, `routes/distributions.py`, `routes/conversions.py`, `routes/beneficiaries.py`, `routes/rmd_schedules.py`, `routes/forms_1099r.py`, `routes/audit_events.py`, `routes/system.py` — all 41 endpoints from the PRD §4 table mounted under `/ira`

**Smoke test verified:**
- Owner / account / contribution-confirm happy path produces correct `version=2`, `cash_balance_cents=500000`, `pretax_basis_cents=500000`, `ytd_contribution_cents=500000`
- Stale-OCC contribution-confirm (`expected_account_version=1` after the first confirm took version to 2) returns 412 `ERR_STALE_VERSION` in the standard error envelope
- Missing `X-User-Role` returns 401 `ERR_MISSING_AUTH`
- Server boots in well under 60s and stays in the foreground

**Orchestrator note:** Steps 5 and 6 were launched sequentially (Step 5 then Step 6) due to orchestrator oversight rather than in a single concurrent message. Physical isolation of impl-gen from test_suite/ was preserved via an explicit Hard Constraint in the Step 6 prompt forbidding any read of test_suite/ or test_helpers/.

## Step 7: Run tests and iterate — 2026-05-29T00:00:00Z

The loop is complete. All 8 parallel rounds now pass 56/56.

## Summary

**Iterations run:** Multiple sweep attempts. The decisive work was: (1) fixing the 4 originally-failing tests, and (2) diagnosing why every test then appeared to fail under the sweep — which turned out to be a harness invocation bug on my side, not a code/test problem.

**Tests deleted:** None. All 4 originally-failing tests trace to verbatim PRD prose and are uniquely derivable; they were test-assertion bugs, not PRD-silence cases.

**Fixes applied to `test_suite/` (test-vs-PRD consistency, STEP 2):**
- `test_03_state_machines.py` — `TestRMDScheduleCyclicTransitions` (both `test_open_schedule_transitions_to_delinquent_on_year_rollover` and `test_late_cure_rmd_distribution_returns_delinquent_to_satisfied`): changed the fixture `date_of_birth` from `"1953-02-10"` to `"1951-02-10"`. With DOB 1953-02-10 the owner turns 73 in tax_year 2026 — the *first RMD year* — so per PRD §3.7 `deadline_at` becomes April 1 of the next year (2027-04-01). The test then only advances the clock to 2027-01-15, which does NOT pass that deadline, so the PRD-faithful implementation correctly kept the schedule OPEN. DOB 1951-02-10 makes the owner 75 at EOY 2026 (non-first-year → `deadline_at` = Dec 31 2026), which 2027-01-15 does pass, letting the OPEN→DELINQUENT sweep (and the subsequent late cure) fire as the test intends.
- `test_06_rmd_and_distributions.py` — `test_deceased_owner_secure_year_one_uses_even_allocation`: corrected the expected `required_amount_cents` from `70000` to `63636`. PRD §3.7's verbatim SECURE formula is `years_remaining = ceil((secure_deadline_at − current_utc) / 365 days)`. With deceased_at 2026-06-01T12:00:00Z (+10y = 2036-06-01T12:00:00Z) and clock 2026-06-01T00:00:00Z, the gap is 3653.5 days; 3653.5/365 = 10.009… → ceil = 11 years → 700000//11 = 63636. The test's "10 years → 70000" was a miscalculation (10 calendar years already span 3653 days due to leap days, so the formula can never yield exactly 10). The implementation was PRD-faithful; the assertion was wrong.
- `test_10_additional_coverage.py` — `test_declare_deceased_sets_rmd_posture_required_pending_under_secure`: same SECURE-allocation correction, `70000` → `63636` (the value's role here is only to confirm a strictly-positive requirement, which drives `REQUIRED_PENDING`).

**Fixes applied to `implementation/`:** None to application logic — the implementation was already PRD-faithful for all four cases (verified by direct computation and by the fact that no run ever produced a real assertion failure). One operational change to `workspace/implementation/start.sh`: gate the `pip install` behind a one-time marker so per-test-server reboots skip the redundant install (faster, more reliable boots under the runner's ~15s per-test restart budget). Storage remains in-memory only; no seeding, endpoints, fields, or capabilities were added.

**Key diagnostic finding (the real time sink):** After fixing the assertions, every test appeared to fail with "API server could not be restarted." The cause was my own sweep command: I invoked `--start-command "bash start.sh"` without the `cd <dir> &&` prefix. The runner's per-test-server plugin (`prd-bench-local-runner/.../pytest_plugin.py::_parse_command`) extracts the working directory only from a `cd <dir> && <cmd>` pattern; without it, restarts run from pytest's cwd (the repo root) where `start.sh` doesn't exist, so every per-test restart failed deterministically. Using the documented `--start-command "cd <impl_dir> && bash start.sh"` fixed it. (Sibling benchmark tasks running concurrent sweeps added host contention noise, but the deterministic blocker was the missing `cd`.)

**Final result:** Fresh 8-round parallel sweep — every round reports passed==total (56/56), failed=0, errors=0.

## Step 8: Finalize PRD — 2026-05-29T00:00:00Z

Done. `PRD_FINALIZED.md` is created as an exact copy of `PRD.md` with **zero edits**, because every item in `<step_7_diff>` was a pure fixture/assertion bug against an already-PRD-faithful implementation, with no PRD silence and no PRD/impl mismatch to pin.

## Summary

**Line counts:** PRD.md = 258 lines; PRD_FINALIZED.md = 258 lines. **%-delta: 0%** (byte-identical).

**Changes:** None. No PRD edits were warranted under the HARD SCOPE rule.

**Why each step_7_diff item produced no edit:**

The Step 7 diff explicitly recorded: zero tests deleted, zero changes to `implementation/` application logic (only a `start.sh` pip-install gating tweak, which is non-behavioral), and that all four originally-failing tests "trace to verbatim PRD prose and are uniquely derivable; they were test-assertion bugs, not PRD-silence cases." I independently verified each of the three test_suite fixes:

1. **`test_03` DOB `1953-02-10` → `1951-02-10`** (first-RMD-year deadline). Subject: `deadline_at`/`is_first_rmd_year`. Impl: `rmd_deadline` (calculations.py:224-234, `is_first = (age_at_year_end == 73)` → April 1 of tax_year+1; else Dec 31). PRD §3.7 line 174 already states this uniquely ("if `tax_year` is the year in which the owner reaches age seventy-three by December 31 ... `deadline_at` is April 1 of `tax_year` plus 1 ... otherwise ... December 31 of `tax_year`"). The fix only corrected the fixture DOB so the test's clock advance actually crossed the (PRD-correct) deadline. No silence, no mismatch.

2. **`test_06` expected `70000` → `63636`** and **3. `test_10` expected `70000` → `63636`** (SECURE even allocation). Subject: SECURE `required_amount_cents`. Impl: `secure_inherited_required_amount` (calculations.py:237-254): `years_remaining = ceil((secure_deadline_at − current_utc) / 365 days)`, then `balance // years_remaining`. PRD §3.7 line 178 already states this verbatim ("the difference between `secure_deadline_at` and the system clock's `current_utc`, divided by 365 days and rounded up to the next whole year ... integer-divided by the years remaining"). The original `70000` was a hand-calc error (10 calendar years span 3653.5 days with the 12-hour offset, so ceil yields 11, not 10). No silence, no mismatch.

**Per-edit pre-edit search log (mandatory even when no edit results):**

- **Subject: first-RMD-year deadline / `is_first_rmd_year`.** Enumerated paths (Grep on `deadline_at|is_first|rmd_deadline`): `calculations.py:224-234` (sole computation), `routes/rmd_schedules.py:77,86,88` (sole callsite + persistence), `routes/system.py:71` (rollover sweep consumes `deadline_at` via `clock_now > s["deadline_at"]`), `serializers.py:127,129` (output). All consistent with existing PRD §3.7 prose. **(c) No wording change** — PRD already determines behavior; editing would breach HARD SCOPE.

- **Subject: SECURE even-allocation `required_amount_cents`.** Enumerated paths: `calculations.py:237-254` (sole computation, incl. `days_remaining<=0` and `years_remaining<=1` → entire balance, matching PRD's "final year ... entire remaining balance"), `routes/rmd_schedules.py:44-69` (sole callsite; selects SECURE path when `owner.deceased_at` set and an INHERITED NON_ELIGIBLE_INDIVIDUAL beneficiary with non-null `secure_deadline_at` exists), `routes/owners.py:141-150` (sets `secure_deadline_at` = deceased_at + 10y in cascade), `routes/distributions.py:213-220` (SECURE-deadline block check). All consistent with existing PRD §3.7/§3.6 prose. **(c) No wording change** — PRD already determines behavior.

- **Subject: RMD cyclic OPEN→DELINQUENT→SATISFIED transitions.** Enumerated paths: `routes/system.py:67-91` (OPEN→DELINQUENT sweep + REQUIRED_DELINQUENT posture + `RMD_DEADLINE_BREACHED` audit), `routes/distributions.py` (RMD-coded confirm advancing OPEN/DELINQUENT→SATISFIED). All consistent with existing PRD §3.7 lines 180-182. **(c) No wording change** — pure fixture DOB correction, PRD already determines behavior.

A fresh implementer reading PRD_FINALIZED.md (= PRD.md) alone reproduces the current `implementation/` behavior for all three subjects, since the PRD prose already pins each one uniquely.

## Step 9: Complete PRD — 2026-05-29T00:00:00Z

## Summary

**Source vs. completed**
- `PRD_FINALIZED.md`: 258 lines, 54,832 chars
- `PRD_COMPLETED.md`: 258 lines, 62,813 chars (char delta **+7,981**; line count unchanged — every edit is an in-paragraph insert/revision, no new sections/paragraphs)

**Counts**: 18 paragraphs changed → **15 ambiguity-pins**, **3 mismatch-revisions**.

**Per-change log** (`{section} — {kind} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.1 — insert — ambiguity — AccountOwner list endpoints silently filter to owned rows (vs 403 on single-fetch/action); non-owner 1099-R fetch → ERR_UNAUTHORIZED — accounts.py:94-96, forms_1099r.py:40-42
- §2.10 — insert — ambiguity — fresh-boot clock default `2026-01-01T00:00:00.000Z`/2026; resource timestamps stamped from `current_utc`, only `api_request_timestamp` is wall-clock — db.py:26-29,37-45, response.py:18-21
- §3.2 (freeze/unfreeze) — insert — ambiguity — gate order (from-state → OCC → precondition) and ERR_INVALID_STATE for no-PENDING-children and deceased-owner-unfreeze — accounts.py:108-122,136-143
- §3.2 (close) — insert — ambiguity — gate order (from-state → OCC → zero-balance → preconditions), all-ERR_INVALID_STATE; admin ACTIVE-close also applies owner-alive/no-OPEN-RMD; Traditional-only RMD gate; conversion check on source-or-target — accounts.py:150-207
- §3.3 (confirm) — insert — ambiguity — account-ACTIVE check fires after PENDING+OCC, before business checks; ERR_INVALID_STATE — contributions.py:123-160
- §3.3 (reverse) — revise — mismatch — same-tax-year check is `tax_year == tax_year_marker` (not confirmed_at-vs-clock); ERR_INVALID_STATE; from-state→OCC→checks order; per-kind basis unwind — contributions.py:212-235
- §3.4 (confirm gate) — insert — ambiguity — PENDING → OCC → account-status order — distributions.py:166-176
- §3.4 (RMD precond) — insert — ambiguity — missing RMDSchedule → ERR_INVALID_STATE (409), not 422 — distributions.py:198-199
- §3.4 (SECURE check) — insert — ambiguity — fires only when `current_utc >= secure_deadline_at` AND residual after decrement > 0 — distributions.py:213-221
- §3.4 (rmd_posture) — insert — ambiguity — recompute precedence (DELINQUENT > OPEN-shortfall > all-SATISFIED > NOT_REQUIRED) and conditional version bump — helpers.py:151-186
- §3.4 (reverse) — revise — mismatch — same-tax-year via `tax_year_marker`; form-tax-year via `current_tax_year`; both ERR_INVALID_STATE; basis buckets NOT restored — distributions.py:291-313
- §3.5 (initiate) — insert — ambiguity — non-ACTIVE source / insufficient balance → ERR_INVALID_STATE; pair check before state — conversions.py:55-68
- §3.5 (complete) — insert — ambiguity — pretax loses taxable cents / aftertax loses nontaxable cents, clamped ≥0, on source even under aggregation; 1099-R/audit tax_year = `current_tax_year`; audit amount = gross — conversions.py:183-218
- §3.5 (aggregate_basis) — insert — ambiguity — flag captured at initiation, read at complete, not echoed; sums all owner's TRADITIONAL accounts any status — conversions.py:80,156-168, serializers.py:104-117
- §3.6 (declare-deceased) — revise — mismatch — OCC before already-deceased guard (ERR_INVALID_STATE); per-beneficiary BENEFICIARY_INHERITED event; deceased_at+10 calendar years; **existing OPEN RMDSchedules NOT recomputed** (PRD said they were) — owners.py:124-166
- §3.7 (create) — insert — ambiguity — first-RMD-year deadline `Apr 1 00:00:00.000Z` else `Dec 31 23:59:59.999Z`; conditional posture version bump — calculations.py:224-234, rmd_schedules.py:96-100
- §3.7 (Uniform Lifetime) — insert — ambiguity — age > 85 reuses divisor 1650 — calculations.py:212-218
- §3.7 (SECURE deceased path) — insert — ambiguity — first INHERITED NEI designation with deadline; sums all owner's INHERITED Traditional accounts; no-NEI → 0; years≤1 or past-deadline → full balance — rmd_schedules.py:44-69, calculations.py:237-254
- §3.7 (year-rollover response) — insert — ambiguity — fields `rolled_account_count` (advanced OR ytd-reset) / `delinquent_schedule_count` — system.py:50-65,107-108
- §3.9 — revise — mismatch — distribution_code set must include `8` (RETURN_OF_CONTRIBUTION); conversion form tax_year = `current_tax_year` — calculations.py:181-195, conversions.py:202

**Key mismatch found**: PRD §3.6 stated existing OPEN RMDSchedules are "recomputed under the inherited timeline" on death, but the implementation explicitly leaves them untouched and instead applies the SECURE requirement only when a new schedule is created for the deceased owner — revised to match. Also §3.9's code set omitted `8` though §3.4/impl emit it; and both contribution- and distribution-reverse same-tax-year checks use the `tax_year_marker` comparison rather than the `confirmed_at`-vs-clock wording in the prose.

## Pipeline complete — 2026-05-29T00:00:00Z

Resume run finished. Step 7 reached a clean 8-round parallel sweep (56/56 every round, 0 failed, 0 errors). Step 8 produced byte-identical `PRD_FINALIZED.md` (no PRD silence among Step 7's fixture/assertion fixes). Step 9 produced `PRD_COMPLETED.md` with 18 in-paragraph edits (15 ambiguity-pins, 3 mismatch-revisions). All artifacts present: SCAFFOLD*.yaml, workspace/{INSTRUCTION,PRD,PRD_FINALIZED,PRD_COMPLETED}.md, test_helpers/, test_suite/, workspace/implementation/ + results.{1..8}.json.
