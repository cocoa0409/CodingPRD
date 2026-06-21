# Worklog — task_0006_school_meal_eligibility

## Step 1: Create task directory — 2026-05-26T00:00:00Z

Created `tasks/task_0006_school_meal_eligibility/workspace/` (pre-allocated ID, no scan needed).

## Step 2: Generate scaffold — 2026-05-26T00:00:00Z

**Scaffold generation summary — task_0006_school_meal_eligibility**

**Files written:**
- `SCAFFOLD.yaml` (§1.0–§1.7 + §1.2.1 concurrency)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** Expert tier; primary archetype `compliance_audit` × secondary `pricing_engine`; flat entity topology; branching state-machine shape with parallel dimensions on EligibilityDetermination; approval_chain RBAC; immediate consistency. Layers: dual-variant calculation, derived-field reconciliation, scheduled actions, optimistic concurrency, rate/threshold triggers, cascading side effects.

**SCAFFOLD.yaml counts:**
- entities: **10** (Household, Student, AllergyProfile, MealApplication, EligibilityDetermination, MenuItem, ParentAccount, LedgerEntry, ServiceTransaction, ReimbursementClaim)
- state_machines: **4** (MealApplication branching+cyclic, EligibilityDetermination parallel-dimension, ServiceTransaction with dispute/refund/compensation, ReimbursementClaim)
- concurrency_rules (OCC): **3** (appeal-stale-application, revoke-stale-determination, refund-stale-transaction)
- calculations: **5** (determine_tier_from_income, compute_paid_charge with 2 variants, compute_claim_reimbursement with 2 variants, select_active_determination, recompute_topup_window)
- validations: **15** priority-ordered rules
- endpoints: **54** (including 3 `/_<name>` test-driving endpoints: clock set, clock advance+expire, auto-renewal)
- errors: **17** (full coverage with boundary-distinguished pairs)
- roles: **5** (Parent entity_backed:Household, SchoolStaff, DistrictReviewer, USDAAuditor, PlatformAdmin — all others opaque)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids × 2 instances each = **18 instances total**. Every rule satisfied with the §0.5 differentiation clause (different entity domains for dual_variant_calc; different modes for combinatorial_formula; different entities for non_linear; etc.).

**SCAFFOLD_CORNER_DESIGN.yaml:** 7 sections, **30 active instances + 7 excluded-because stubs** (those overlapping §1.8 are stubbed to point at the difficulty instance). Active coverage includes all 9 unique error_ids not asserted as primary in §1.8 (UNAUTHENTICATED, FORBIDDEN×3 role denials, NOT_FOUND, INVALID_REQUEST, INVALID_PAGINATION, INSUFFICIENT_FUNDS, DUPLICATE_IDEMPOTENCY_KEY, STALE_VERSION×3, ALLERGEN_CONFLICT direct trigger), plus entity defaults, computed fields, system fields, invalid transitions, terminal lockdowns, auto-renewal sweep, pagination meta, FK-filter listing.

**Lint verdict** (`python3 scaffold_lint.py task_0006_school_meal_eligibility/`): clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5. 309 setup/trigger calls scanned across both design files; zero violations.

## Step 3: Copy INSTRUCTION.md — 2026-05-26T00:00:00Z

Copied root `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-05-26T00:00:00Z

- **Output:** `workspace/PRD.md`, 313 lines.
- **Sections covered:** §1 Introduction (2 paragraphs framing FRL/district/USDA pain points); §2 Global Specs with 10 subsections — 2.1 RBAC + role identities, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Common Properties (with `LedgerEntry`-as-immutable exception called out), 2.5 OCC (all 3 concurrency rules), 2.6 Monetary Precision, 2.7 Time/Server Clock, 2.8 Path Hierarchy, 2.9 Ledger principle, 2.10 Validation ordering; §3 Business Logic with 8 subsections organized by entity-cluster lifecycle (Households+Students+AllergyProfiles → Application lifecycle → Tier calc on approval → Eligibility 2-dimension lifecycle → MenuItems+ServiceTransaction creation/pricing → Funding/Settlement/Disputes/Refunds → Reimbursement claims → Admin capabilities); §4 endpoint table (4 cols, 53 rows); §5 error catalogue (2 cols, 17 rows).
- **Hard Contract 1 (Field-Name Coverage):** 61 required, 61 present, 0 missing — PASS. (One repair pass needed: `parent_account_id` was missing from the §2.9 ledger paragraph; added.)
- **Hard Contract 2 (Rule Coverage):** All categories walked — 3 OCC rules, ~25 state transitions, 5 calculations, 15 validations with priority order in §2.10, all `applies_to` scopes named, sibling pairs (approve/deny, REFUND/UPHOLD, finalize/reject claim, withdraw-from-DRAFT/SUBMITTED, start-review-from-SUBMITTED/APPEALED) given equal density — PASS.
- **Hard Contract 3 (§3 Path Purity):** 442 §3 backtick tokens scanned, 0 violations after fix. (One repair pass needed: §3.8 originally said "Three endpoints under the `/_clock/` and `/_renewal/` namespaces"; rewritten to "Three administrative capabilities … clock-set, advance-and-expire, and auto-renewal sweep". The two earlier mentions of those namespaces in §2.1 and §2.7 are kept — Contract 3 polices §3 only.)
- **Tightening done before prose could pin behavior:** none — the scaffold was fully self-consistent.

## Step 5: Generate unit tests — 2026-05-26T00:00:00Z

**test_helpers/** (9 files):
- `__init__.py` — Barrel export of framework + PRD-specific
- `types.py` — TypedDicts and enums (LedgerEntry has only id+created_at per common_fields:false)
- `api_client.py` — One method per PRD endpoint (51 methods)
- `api_errors.py` — All 17 error IDs + HTTP status map; registers with framework
- `assertions.py` — `assert_<entity>(data)` for each of 9 entities
- `factories.py` — Payload factories for every input-bearing endpoint
- `constants.py` — FPL tables, percentages, surcharge/cap constants
- `test_users.py` — `TEST_USERS` shared constants + `make_parent_headers(household_id)` for entity_backed Parent
- `fixtures.py` — Low-level wrappers (set_clock, create_*, settle/refund/dispute) + composite fixtures (`setup_direct_cert_household`, `setup_approved_application`, `setup_denied_application`, `setup_pending_transaction`, `setup_settled_transaction_paid_tier`, `setup_two_claims_scenario_setup`); resolves `parent_account_id` via the PRD-required nested `/households/{id}/parent-account` read.

**test_suite/** (16 files including conftest):
- `conftest.py` — Pytest fixtures for api + role headers
- 15 `test_*.py` files containing **66 total test functions**.

**Coverage audit:**
- **Difficulty (queue A):** 18 instances × 2 tests each = **36 tests** — all 9 rules' 18 instances translated, no skips.
- **Corner (queue B):** **30 tests** covering all non-stub instances:
  - errors: 12/12 translated
  - entities: 5/5 translated
  - state_machines: 4/4 translated
  - rbac: 3/3 translated
  - endpoints: 5/5 translated (including auto-renewal sweep, idempotent replay, ledger filter by linked_transaction_id, paginated meta, nested-read filter)
  - calculations: 1/1 translated
  - validations: 7/7 are `excluded_because:` stubs — correctly NOT translated; difficulty-instance cross-references verified.

**Skipped instances:** 0 — every non-stub instance from both indices passed the PRD-first two-condition filter (verbatim PRD coverage + unique derivability) and produced a tagged test. All test docstrings carry a verbatim PRD citation (grep-validated against PRD.md) and end with the `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` tag copied verbatim from the source yaml.

**Sanity checks:** All 9 helper files and all 15 test files pass `python3 -m py_compile`; `test_helpers` package imports cleanly.

## Step 6: Generate implementation — 2026-05-26T00:00:00Z

# Implementation Summary — task_0006_school_meal_eligibility

## Files Written (18 total, 2,282 lines)

### Infrastructure
- `start.sh` (5 lines) — bash launcher, `exec`s python3 app.py, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` (1 line) — Flask 3.0.3 only
- `app.py` (76 lines) — Flask entrypoint, blueprint registration, global error handlers (`ApiError`, 404, 405, 400, generic)

### Core modules
- `errors.py` (34 lines) — `ApiError` class + 17 error tuples from PRD §5
- `response.py` (90 lines) — envelope helpers (`success_object`, `success_array`, `error_response`), `iso_utc` (ISO 8601 UTC with 3 fractional digits, Z suffix), `parse_iso_utc`
- `db.py` (52 lines) — empty in-memory dicts per entity + settable server clock (`server_now()`/`set_clock()`)
- `middleware.py` (34 lines) — `get_auth()`, `require_role()`, parent-ownership check
- `validation.py` (75 lines) — pagination parsing (limit∈[1,100], offset≥0), JSON body parsing, key enforcement, type guards
- `calculations.py` (130 lines) — `determine_tier_from_income` (FPL tables for CONTIGUOUS/ALASKA/HAWAII, family_size 1..8, half-up÷12 then floor thresholds, inclusive ≤), `compute_paid_charge` (FREE=0 / REDUCED=min(40, round_half_up(0.10·list)) / PAID=list, +25¢ allergen surcharge when applicable and tier≠FREE), `DAILY_TOPUP_CAP_CENTS=20000`
- `services.py` (181 lines) — `common_fields_init` (id, created_at, updated_at, version=1 + `_created_at_dt` private), `bump_version`, `select_active_determination` (sort: tier_priority DESC, valid_from DESC, created_at DESC — never id), `cascade_allergen_check_for_student`, `school_year_end_plus_carryover` (June 30 +30 days), `compute_balance` (ledger sum), pagination, `clean()` strips `_*` private fields

### Route modules (one per resource group)
- `routes/households.py` (197 lines) — POST/GET/PATCH/list + 4 nested reads; create auto-spawns ParentAccount(balance=0)
- `routes/students.py` (144 lines) — Student CRUD + AllergyProfile create/PATCH with cascade
- `routes/applications.py` (271 lines) — full lifecycle: submit/start-review/approve (with full 3-depth cascade: supersede prior ACTIVE → re-bind PENDING txns with new tier+paid_charge)/deny/appeal (OCC)/withdraw
- `routes/eligibility.py` (170 lines) — operator-create (rejects `APPLICATION` source for direct creation), verify/defer (require ACTIVE+UNVERIFIED), revoke (OCC), AUTO_RENEWAL EXPIRE side effect
- `routes/menu_items.py` (79 lines) — CRUD + list filterable by school_code
- `routes/parent_accounts.py` (143 lines) — read (reconciles balance from ledger), top-up (idempotency + daily window roll + cap check), ledger list + read
- `routes/service_transactions.py` (302 lines) — create (allergen safety, select_active_determination, compute_paid_charge, stamp served_at_utc), settle/reject/refund(OCC)/dispute/resolve-dispute(REFUND|UPHOLD)
- `routes/reimbursement_claims.py` (172 lines) — create (with overlap + 1-day-gap rule), submit (gated by closure rule + CASH vs ACCRUAL aggregation), finalize, reject
- `routes/admin.py` (126 lines) — `_clock/set_current_utc`, `_clock/advance_and_expire` (sweeps ACTIVE→EXPIRED for `valid_to_utc<=now`), `_renewal/run_auto_renewal` (carries forward most-recent tier per household)

## Notable Design Choices Where the PRD Permitted Latitude

1. **AUTO_RENEWAL sweep on overlap conflict** — PRD §3.8 says auto-renewal is "subject to the household-window non-overlap rule of §3.4". I treat each household independently: a window-overlap for one household skips that household but does not abort the whole sweep. The response only counts successfully-renewed households.

2. **`X-User-ID` always required** — PRD §2.1 mandates both `X-User-Role` and `X-User-ID` on every request; I reject with `ERR_UNAUTHENTICATED` if either is missing. For opaque operator roles the value is recorded but not compared to any entity.

3. **`address_state` validation** — Enforced as exactly two uppercase ASCII letters. The PRD says "two-letter uppercase US state code"; I do not validate the alphabet against a closed enumeration (any AA..ZZ is accepted), only the shape, since the FPL region map falls back to CONTIGUOUS for any non-AK/HI value as the scaffold's `_default` rule prescribes.

4. **School-year-end derivation** — PRD §3.3: "end of the school year plus a 30-day carryover" without a calendar definition. I use **June 30 of the latter year, 23:59:59.999 UTC + 30 days** as the canonical SY-end.

5. **ServiceTransaction creation stashes `substitute_for_allergen`** as a private attribute (`_`-prefixed in spirit; cleaned from responses) so the approval cascade can recompute `paid_charge_cents` with the original substitution flag. The PRD does not list this on the entity.

6. **Family-size beyond table** — FPL tables only tabulate 1..8. For `snapshot_family_size>8` I fall back to row 8 defensively (the scaffold's hard cap is 20 but provides no rows for 9..20). Tests are expected to stay within 1..8.

7. **Overlap check on application-approval** — Run AFTER prior ACTIVE determinations have been superseded (their `valid_to_utc` set to now), so the new window (start=now) can immediately succeed the just-superseded window without overlap.

8. **`ERR_FORBIDDEN` vs `ERR_NOT_RESOURCE_OWNER` ordering** — Parents are present in the allowed-role set for read endpoints, so they pass the FORBIDDEN check, then the ownership check returns `ERR_NOT_RESOURCE_OWNER` (403) when they target someone else's resource. This matches the PRD §2.10 ordering (auth → role → ownership).

## Verification

Boot tested with `PORT=10876 python3 app.py`. Confirmed:
- 54 routes registered (covers all PRD §4 endpoints).
- Missing `X-User-Role` → 401 `ERR_UNAUTHENTICATED` with proper envelope.
- POST household → 201, auto-creates ParentAccount visible via nested read.
- Application submit→start-review→approve produces an `APPLICATION`-source `EligibilityDetermination` with `tier=FREE` for family_size=4 / annual_income=$30,000 / state=CA (FPL_monthly=$2,600; household_monthly=$2,500 ≤ free-tier ceiling $3,380 → FREE). All version bumps and timestamps refreshed correctly.

## Step 7: Run tests + iterate — 2026-05-26T00:00:00Z

**Iterations run:** 2 (initial diagnostic + post-fix verification, with one additional verification after start.sh tweak — total 3 sweeps × 8 parallel rounds).

**Tests deleted:** 0. (The original `test_accrual_basis_includes_settled_disputed_and_refunded` was rewritten as `test_accrual_basis_includes_settled_and_refunded` per STEP 1c partial-coverage split — the DISPUTED branch of ACCRUAL aggregation is unreachable via faithful PRD submission because PRD §3.7's closure rule blocks claim submission while DISPUTED transactions exist in the period; the SETTLED+REFUNDED branches are still exercised and remain PRD-verbatim.)

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `setup_two_claims_scenario_setup` no longer disputes tx4 (DISPUTED in period would block claim submission per §3.7 closure rule). The fixture now produces 3 SETTLED + 1 REFUNDED, leaving the claim submittable.

**Fixes applied to test suite (faithfulness corrections, not deletions):**
- `test_suite/test_06_validation_priority.py` — `test_parent_topping_up_other_household_over_cap_reports_not_resource_owner` now resolves `hh_b`'s parent_account_id via the PRD §2.8 nested read instead of assuming `household.id == parent_account.id` (PRD never establishes that equivalence; test_helpers's `resolve_parent_account_id` documents this explicitly).
- `test_suite/test_10_reimbursement_aggregation.py` — both CASH and ACCRUAL aggregation tests updated to match the corrected fixture (3 SETTLED + 1 REFUNDED, totals = 1410, counts = 3 for CASH / 4 for ACCRUAL). Test renamed `test_accrual_basis_includes_settled_disputed_and_refunded` → `test_accrual_basis_includes_settled_and_refunded` to reflect the reachable assertion set.

**Fixes applied to `implementation/`:**
- `implementation/routes/service_transactions.py` — `refund_transaction` now checks `expected_servicetransaction_version` BEFORE the SETTLED state precondition. PRD §2.5 (line 90) explicitly says the OCC guard captures the case where a transaction "has advanced — for example, into DISPUTED — since the staff member's read"; this requires OCC to win over ERR_INVALID_STATE on that pathway.
- `implementation/routes/admin.py` — `run_auto_renewal` now considers prior determinations in `ACTIVE`, `SUPERSEDED`, OR `EXPIRED` lifecycle status. PRD §3.8 says "held an ACTIVE or SUPERSEDED determination in the prior school year" — past tense + temporal qualifier — so a determination that was ACTIVE in the prior year but has since been EXPIRED by the natural advance-and-expire sweep still qualifies. Without this inclusivity, auto-renewal cannot serve its stated operational purpose of renewing households at the start of a new school year, after the prior year's windows have closed.
- `implementation/start.sh` — skip `pip install` when Flask is already importable, dramatically speeding up per-test-server restarts and eliminating the rare BadStatusLine flake seen in round 4 of the post-fix sweep.

**Final status:** 8/8 parallel rounds, 66/66 tests pass per round.

## Step 8: Finalize PRD — 2026-05-26T00:00:00Z

- PRD.md: 313 lines. PRD_FINALIZED.md: 313 lines. Delta: 0 lines (0.0%); two lines revised in place.

Changes (one per Step 7 implementation-side fix that pinned a PRD ambiguity):

- §2.5 (Optimistic Concurrency Control) — revise — appended a sentence pinning that the refund OCC version check is evaluated *before* the `SETTLED` state-machine precondition, so a stale-view refund against a now-`DISPUTED` transaction surfaces `ERR_STALE_VERSION` rather than `ERR_INVALID_STATE` (overrides the generic §2.10 ordering for this endpoint only) — `implementation/routes/service_transactions.py:230-238` (`refund_transaction`).
- §3.8 (Administrative Capabilities: Clock and Auto-Renewal) — revise — expanded the candidate set for auto-renewal from "`ACTIVE` or `SUPERSEDED`" to "`ACTIVE`, `SUPERSEDED`, or `EXPIRED`" prior determination, explained that the most-recent prior determination is selected per household by latest `valid_from_utc`, and pinned that a per-household overlap during the sweep silently skips that household (no error, sweep continues) — `implementation/routes/admin.py:67-103` (`run_auto_renewal`, with the household selection and per-household overlap-skip behavior).

Items from Step 7 not pinned in PRD (correctly so):
- `test_helpers/fixtures.py` (`setup_two_claims_scenario_setup`) — fixture bug; PRD §3.7 closure rule is already explicit. No PRD change.
- `test_suite/test_06_validation_priority.py` (`resolve_parent_account_id`) — test-helper bug; PRD §2.8 already requires nested-read resolution. No PRD change.
- `implementation/start.sh` — pure operational optimization (skip `pip install` when Flask is already importable); no behavioral surface. No PRD change.

