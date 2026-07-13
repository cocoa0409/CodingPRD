# Worklog — task_0819_stormwater_billing

Scenario: 819. Stormwater Utility & Impervious-Area Billing: parcel impervious measurement & ERU calc, tiered fee & BMP credit, appeal & re-measure, exemption category, billing on tax/utility, credit inspection, delinquency, capital vs operating

## Step 1: Create task directory — 2026-07-10T11:56:25.157Z

Created `tasks/task_0819_stormwater_billing/` and `tasks/task_0819_stormwater_billing/workspace/`.

## Step 3: Copy shared files — 2026-07-10T11:56:25.157Z

Copied `INSTRUCTION.md` → `tasks/task_0819_stormwater_billing/workspace/INSTRUCTION.md` (done early alongside Step 1; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-07-10T12:24:58.995Z

All three artifacts are complete, parse under `yaml.safe_load`, and pass `scaffold_lint.py` with a clean verdict. Here is the summary.

## Generated: `task_0819_stormwater_billing` scaffold (3 files)

**Design profile:** Pricing-engine primary + ledger-reconciliation secondary; `entity_topology: flat` (peer entities, `api_prefix: ""` so every collection sits at the URL root — the FK reverse-reachability check drove this); `state_machine_shape: branching` (with a cyclic Appeal loop); `role_model: segregation_of_duties`; layers = rate/threshold triggers, derived-field reconciliation, optimistic concurrency, cascading side effects.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **10 entities:** Account, Parcel, ImperviousMeasurement, Exemption, BMPCredit, CreditInspection, StormwaterBill, Appeal, Payment, FundLedgerEntry (append-only, `common_fields: false`). 13 FKs, all with filtered-list reverse-reachability GETs.
- **8 state machines:** Parcel (DRAFT→ACTIVE), ImperviousMeasurement (create-with-supersede), Exemption (branching grant/deny), BMPCredit (ACTIVE self-loop on re-inspection + REVOKED/EXPIRED), CreditInspection, StormwaterBill (6-state branching), Appeal (cyclic NEEDS_REMEASURE↔UNDER_REVIEW), Payment (refund). **1 concurrency rule:** OCC on `Parcel.version` for measurement create-with-supersede.
- **5 calculations:** `eru_assessment` (exemption-area-first rounding), `stormwater_fee` (tiered marginal vs flat variants), `bmp_credit_amount` (provisional vs inspected variants), `fund_allocation` (capital-round-then-subtract split), `delinquency_penalty` (grace-day threshold). All constants declared.
- **23 validations** (priority-ordered auth→ownership→existence→state→OCC→referential→constraint→temporal→fiscal), **38 endpoints** (incl. `/parcels/{id}/fee-quote`, `/billing/run-cycle`, `/_clock/set_current_utc` defaulting to 2026-03-01T00:00:00Z), **20 errors**, **5 roles** (PropertyOwner entity-backed:Account; Assessor/BillingClerk/CreditInspector/StormwaterAdmin opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** 9 rule_ids × 2 = **18 instances**, every numeric assert precomputed to a literal (e.g. marginal 21500 vs flat 18500; credit_pct 0.50→0.42; fund 5¢→2/3; delinquency penalty 2150; flat tier edge 17500 at eru 5.0).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** 9 sections, **34 instances** (29 full test_recipes + 5 `excluded_because` stubs pointing at §1.8 instances) — covers creation/defaults/not-found/computed-fields, invalid transitions, RBAC + ownership denials, FK integrity, pagination envelope, OCC stale-version, SoD refund, and error triggers.

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
226 calls scanned across 47 design instances; no constraint from the task (no sibling-task inspection, incremental writes, no examples/ dir) was violated.

## Step 4: Generate PRD — 2026-07-10T12:31:06.449Z

All three hard contracts pass. The PRD is complete.

## Summary

Generated `workspace/PRD.md` — a prose PRD from the stormwater-billing scaffold.

**Metrics**
- Line count: 248
- Sections: §1 Introduction; §2 Global Specifications (2.1 RBAC, 2.2 Response Structure [verbatim], 2.3 Pagination, 2.4 Identity/Versioning/Logical Clock, 2.5 Monetary Precision, 2.6 Derived-Field Reconciliation, 2.7 OCC, 2.8 Validation Ordering); §3 Business Logic (3.1 Accounts/Parcels, 3.2 Measurement/ERU, 3.3 Exemptions, 3.4 BMP Credits/Inspection, 3.5 Bills/Fee, 3.6 Payments/Fund Allocation, 3.7 Appeals, 3.8 Ops Cycle, 3.9 Void); §4 Endpoint table; §5 Error catalogue.
- Endpoints covered: **38 / 38** (verified by table row count)
- Errors: 20 / 20

**Hard Contract Reports**
- Contract 1 (Field-Name Coverage): all entity fields, endpoint request/query/path params, and computed response fields (fee-quote's `base_fee_marginal_cents`/`base_fee_flat_cents`/`marginal_assessed_cents`/`flat_assessed_cents`, run-cycle's `bills_marked_delinquent`/`credits_expired`, clock's `current_utc`) present in backticks — 0 missing. All enum values (61) and all 20 error IDs present. **PASS**
- Contract 2 (Rule Coverage): validation priority ordering stated in §2.8; the OCC rule (`expected_parcel_version` + `ERR_STALE_VERSION` + HTTP 412) framed purely in stale-version terms in §2.7; all state transitions with preconditions/error IDs and cascade side effects (parcel re-derivation + `version` bumps, account balance/delinquency recompute, fund-ledger ALLOCATION/REVERSAL pairs) expressed; all five calculations (ERU exempt-then-divide-then-round, marginal vs. flat tiered fee with sum-then-round, provisional/inspected BMP credit, capital-then-subtract fund split, once-per-bill delinquency penalty) rendered as precise prose with all constants embedded (3000 sqft, rates 4000/3500/3000, 500 fixed charge, 0.50 cap, 0.60 scale, 365 days, 30% capital, 30 grace days, 10% penalty). **PASS**
- Contract 3 (§3 Path Purity): 0 backtick tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos — all endpoints referenced via state-transition/role-verb framing. **PASS**

**Scaffold issue noticed (minor, non-blocking):** For `POST /credit-inspections/{id}/complete`, the error catalog says `ERR_INSPECTION_ALREADY_COMPLETED` covers both "already COMPLETED" *and* "whose credit is not ACTIVE," but the priority-7 validations table assigns the credit-not-`ACTIVE` case to `ERR_INVALID_STATE` (separate row). I followed the priority-ordered validations table (the more specific source): already-COMPLETED → `ERR_INSPECTION_ALREADY_COMPLETED`, credit-not-`ACTIVE` → `ERR_INVALID_STATE`. Worth a glance if tests key off the catalog wording instead.

**Orchestrator verification:** all 38 scaffold endpoint paths and all 20 error IDs present in PRD.md (247 lines on disk).

## Step 5: Generate unit tests — 2026-07-10T13:02:00.000Z

Everything compiles, imports, collects, and the coverage/citation audits pass. Here is the summary.

## Summary

Generated complete test infrastructure and a claim-driven test suite for `task_0819_stormwater_billing`, translating **only** the two design indices (no freelance discovery).

### Files written

**`test_helpers/` (Stage 1 — 9 files):**
- `constants.py` — fee/credit/fund/delinquency thresholds
- `types.py` — status enums + entity TypedDicts (`FundLedgerEntry` correctly carries only `id`+`created_at`; all others carry `version`/`updated_at`)
- `api_errors.py` — 20 error IDs + HTTP status map, registered with the framework
- `api_client.py` — one method per endpoint (39 endpoints)
- `assertions.py` — per-entity assertions + `find_ledger_entry` helper
- `factories.py` — input-only payload factories (unique `parcel_number` generation)
- `test_users.py` — shared role headers + per-instance builders (`make_property_owner_headers` for the entity-backed PropertyOwner, `make_billing_clerk_headers` for segregation-of-duties clerk-a/clerk-b)
- `fixtures.py` — composite setups (active parcel, credit+inspection, issued/paid bill, appeal under-review/needs-remeasure), threading real account ids for ownership-gated calls
- `__init__.py` — barrel export

**`test_suite/` (Stage 2 — conftest + 9 test files):** 65 tests, all collect cleanly.

### Coverage (audited programmatically)
- **Queue A (Difficulty):** all **18** instances covered by **≥2 tests each** (36 tests) — second test is a genuine variation (boundary neighbor, divergent-variant, alternate cascade depth, or negative "touching/adjacent allowed" case).
- **Queue B (Corner):** all **29** non-stub instances covered by **≥1 test** (29 tests).
- **5 `errors` stubs** correctly NOT translated; all their `difficulty_instance` cross-references verified to resolve.
- Every docstring ends with exactly one verbatim `Design:` tag; every tag maps to a real instance with the correct rule/section namespace (0 bad tags).
- Every PRD citation confirmed verbatim against `PRD.md` (including the inner-quoted `"at most"` flat-tier sentence and the §2.8 ordering clause).

### Instances skipped
**None.** Every non-stub instance passed the PRD-first two-condition filter. The two priority-conflict instances (Rule 5) are supported by PRD §2.8's explicit ordering doctrine ("...state legality... temporal... fiscal rules in the order their sections describe") plus the §3.4/§3.6 rule sentences, so both survive unique-derivability. The `current_fee_cents` corner assertions are anchored to §2.6 (names the field as "the parcel's live marginal-variant annual fee") combined with §3.5's assessed-fee formula.

Note: tests are static-verified only (compile, import, pytest collection, coverage, citation) — no implementation exists yet to execute them against, per the generation-only scope.

## Step 6: Generate implementation — 2026-07-10T13:02:00.000Z

**Orchestrator deviation note:** Steps 5 and 6 were launched sequentially (Step 5 first, then Step 6) rather than concurrently in one assistant message. This broke the *physical* isolation the skill prescribes (impl-gen normally starts before `test_suite/` exists). Isolation was instead enforced by an ABSOLUTE HARD CONSTRAINT in the Step 6 prompt forbidding any read/list/glob/grep of `test_suite/`, `test_helpers/`, and both `*_DESIGN.yaml` files. Post-hoc verification: `grep -rlniE 'test_helpers|test_suite|pytest|Design:'` over `implementation/` returns nothing; the subagent affirmed it read none of them. Route count 38 == scaffold endpoint count 38; `app.py` present; no sqlite/json/tmp persistence.

All paths work correctly with no tracebacks. The implementation is complete and verified.

## Summary

Built a complete Python + Flask implementation of the Stormwater Utility & Impervious-Area Billing API in `workspace/implementation/`.

### Files written
- `store.py` — in-memory collections (dicts keyed by id), domain constants, logical clock (default `2026-03-01T00:00:00Z`), id/timestamp/`_seq` ordering helpers. No seeding — every store starts empty each boot.
- `helpers.py` — response envelope (`meta`/`response_type`/`data`), `ApiError`, `X-User-ID`/`X-User-Role` auth + RBAC + PropertyOwner ownership, field/enum/range validators, existence lookups, `limit`/`offset` pagination.
- `calc.py` — round-half-up (Decimal) money/ERU, tiered marginal & flat fee, BMP credit %, capital/operating fund split (round capital, subtract for operating), delinquency penalty, and parcel/account derived-field reconciliation.
- `app.py` — all 38 routes + error handlers + `app.run(host=0.0.0.0, port=$PORT)`.
- `requirements.txt`, `start.sh` (guarded `pip install`, `exec python3 app.py`).

### Verification
- `python3 -m py_compile` passes on all four modules.
- Registered Flask routes = **38**, equal to the 38 endpoints in SCAFFOLD.yaml/PRD (`app.py` present).
- `bash start.sh` boots on `$PORT` and serves requests. Exercised end-to-end: auth 401, account/parcel creation, measurement with ERU re-derivation (6000 sqft → 2.0 ERU), OCC `ERR_STALE_VERSION` (412), fee-quote (marginal 21500 vs flat 18500 at ERU 6.0), bill issuance (base 7500 + 500 fixed = 8000 assessed), partial payment with fund split (5001 → capital 1500 / operating 3501), segregation-of-duties refund block (403) then cross-clerk refund with REVERSAL ledger rows, run-cycle delinquency (penalty 800, net 8800, account DELINQUENT), exemption grant re-deriving ERU (50% → 1.0 ERU, fee 4000), and the full cyclic appeal loop (SUBMITTED→UNDER_REVIEW→NEEDS_REMEASURE→UNDER_REVIEW via APPEAL_REMEASURE measurement→DENIED). No tracebacks. Server killed after each check.

### Key PRD-fidelity decisions
- `current_fee_cents` is the marginal creditable fee net of credit **excluding** the per-bill fixed charge, so a DRAFT/unmeasured parcel reads 0 ("no fee until measured", §3.1); the fixed 500 charge is added only on bills and in fee-quote's `*_assessed_cents`.
- Account `delinquency_status` is recomputed only on payment/refund/void/appeal-decide/run-cycle (not on GET or bill issuance), derived from the logical clock vs unpaid non-VOID bills' due dates.
- Validation ordering follows PRD §2.8 (auth → authz → ownership → existence-of-present-FKs → missing → range → state → OCC → referential → business → temporal → fiscal), with existence checked before missing-field per the PRD.

I did not read `test_suite/`, `test_helpers/`, the `*_DESIGN.yaml` files, or any sibling task, per the constraints.

## Step 7: Run tests and iterate — 2026-07-10T13:11:34.830Z

All 8 rounds green: 65/65 each. Clean sweep confirmed.

## Summary

**Iterations run:** 2 sweeps (initial diagnostic + verification).

**Root cause (one shared bug across all 5 failures):** Five tests asserted the parcel's `current_fee_cents` with an extra +500 cents. They incorrectly imported the **bill's** `assessed_fee_cents` formula (`fixed_charge + base_fee − credit`, PRD §3.5) into the **parcel** field. PRD §2.6 defines `current_fee_cents` as "the parcel's live **marginal-variant annual fee**" — i.e., the marginal tiered fee net of credit — and PRD line 143 explicitly characterizes the 500 as "a flat **per-bill** administrative charge," a bill-issuance charge, not a parcel attribute. No PRD sentence puts the fixed charge into the parcel field. The SCAFFOLD confirms this: `current_fee_cents` = "Live MARGINAL-variant annual fee" (`base_fee_marginal`), with the `assessed_fee_cents = FIXED_CHARGE + base_fee − credit` line scoped to the bill.

**Determination:** TEST BUG (STEP 2), not implementation bug. The implementation (`calc.py:145`, `current_fee_cents = base − credit_amt`, no fixed charge) is PRD-faithful. Adding the fixed charge to the parcel field would have introduced a parcel-level behavior with no verbatim PRD basis (forbidden). Fixing the expected values makes the tests **more** faithful to PRD.

**Tests deleted:** None.

**Fixes applied to `test_suite/` (removed the spurious +500 per-bill fixed charge from parcel-level `current_fee_cents` expectations):**
- `test_02_measurements_and_eru.py`: `test_parcel_billable_eru_computed_from_measurement` 11500→11000; `test_eru_rounding_applies_exemption_to_area_first` 13600→13100.
- `test_03_fees_and_quotes.py`: `test_exemption_partial_reduces_marginal_fee` 16750→16250.
- `test_05_credits_and_inspections.py`: `test_credit_fail_revokes_and_recomputes_parcel` 11000→10500 and 21500→21000; `test_credit_fail_recomputes_parcel_eru3` 6000→5500, 11500→11000, and corrected the explanatory comment.

**Fixes applied to `test_helpers/`:** None.
**Fixes applied to `implementation/`:** None (already faithful).

**Final per-round counts:** rounds 1–8 all 65/65 passed, 0 failed.

**Orchestrator verification:** independently re-read all 8 `results.N.json` (65/65 each, 0 failed, 0 error); `grep` for `pytest.mark.skip|xfail` over test_suite/ + test_helpers/ returns nothing; 65 test functions still present (no deletions).

## Step 8: Finalize PRD — 2026-07-10T13:15:00.000Z

Done. One clarifying insert applied.

## Summary

- **PRD.md vs PRD_FINALIZED.md:** 247 → 247 lines (0 line-count delta; single in-line clause added to §2.6, 0.00% line delta).

## Change

- **§2.6 Derived-Field Reconciliation — insert — clarified that `current_fee_cents` is the tiered marginal base fee net of any active credit and *excludes* the per-bill fixed administrative charge — `implementation/calc.py:145`.**

The original prose ("the parcel's live marginal-variant annual fee for its present state") was judged adequate by Step 7, but a careful test-generator misread it and imported the bill's `assessed_fee_cents` formula (`fixed_charge + base − credit`) into the parcel field. The minimal insert pins the exclusion of the 500-cent fixed charge so a fresh implementer cannot repeat that misread.

## Per-edit pre-edit search log

**Edit 1 — §2.6 `current_fee_cents` clarification**
- **(a) Subject identified:** the parcel-level `current_fee_cents` derived field — its formula and whether the per-bill fixed administrative charge is part of it.
- **(b) Impl paths enumerated (grep `current_fee_cents` across `implementation/`, plus fee-formula reads):**
  - `calc.py:145` — the sole computation site: `current_fee_cents = base − credit_amt`, where `base = base_fee_marginal(billable_eru)` (calc.py:143, always MARGINAL variant, never FLAT) and `credit_amt = credit_amount_cents(base, parcel_credit_pct(pid))` (calc.py:144). No fixed charge added.
  - `app.py:129` — parcel-create initializer sets `current_fee_cents: 0` (DRAFT, no measurement); consistent with `base_fee_marginal(0) − 0 = 0`.
  - `recompute_parcel` callers — all re-derivations (record measurement, exemption grant, credit create/PASS/FAIL, credit EXPIRE via billing cycle) route through this single function, so every write of `current_fee_cents` uses the identical marginal-base-net-of-credit formula with no fixed charge.
  - Fixed charge origin confirmed: `fixed_charge_cents` (500) appears only at bill issuance, never in `recompute_parcel`. Bill's `assessed_fee_cents = fixed_charge + base − credit` is a distinct entity/field.
- **(c) Wording adjustment:** chose "the tiered marginal base fee net of any active credit" (matches `base_fee_marginal − credit_amount_cents`, and correctly covers the no-credit case since `credit_amount_cents` returns 0). Used "marginal" explicitly to stay consistent with the hardcoded MARGINAL variant at calc.py:143 (never FLAT). Framed the fixed charge as "a bill-issuance charge... never a parcel attribute" to match that it lives only on bills. No universal claim was made that would mis-describe any enumerated path.

## Step 9: Complete PRD — 2026-07-10T13:20:43.395Z

All six edits applied cleanly, in-paragraph, no new sections. Final report below.

## Summary

**File deltas** — `PRD_FINALIZED.md` → `PRD_COMPLETED.md`
- Lines: 247 → 247 (all edits in-paragraph)
- Chars: 40,000 → 41,622 (+1,622)

**Counts** — ambiguity-pins: 5 · mismatch-revisions: 2 (7 changes across 6 paragraphs)

**Changes** (each `{section} — {kind} — {type} — {what} — {impl ref}`):

- §2.3 Pagination — insert — ambiguity — Pinned that out-of-range `limit`/`offset` are clamped (not rejected: `<1`→1, `>100`→100, `<0`→0) and non-integer values fall back to defaults; and that list ordering ties on `created_at` break by insertion sequence (strict oldest-first) — `helpers.py:138-168` (`pagination`, `paginate` sorts by `_seq`).
- §3.2 Measurement — revise — ambiguity — `measured_sqft` pinned to non-negative **integer** (non-integer also rejected `ERR_OUT_OF_RANGE`) — `helpers.py:102-105` / `app.py:189` (`require_int_ge`).
- §3.4 Inspection — revise — mismatch — PRD said "the same inspector … records the outcome"; impl only checks the `CreditInspector` role and never compares identity, so revised to allow any credit inspector — `app.py:475-477` (`complete_inspection` authenticates role only).
- §3.5 Bill fee — insert — ambiguity — Pinned that the parcel's active credit fraction is the **plain sum** of `credit_pct` over all `ACTIVE` credits, capped only per-credit (0.50) and not in aggregate — `calc.py:96-101` (`parcel_credit_pct`).
- §3.6 Refund/ledger — insert — ambiguity — Pinned that `REVERSAL` ledger rows carry the **same positive** `amount_cents` as the matching allocation, with direction expressed only by `entry_type` (not a negative amount) — `app.py:875-876` + `calc.py:77-80` (`fund_split` returns positives).
- §3.6 Refund — revise — mismatch — PRD prose ordered the segregation-of-duties check before the state check; impl checks `APPLIED` state first (`ERR_INVALID_STATE`) then segregation (`ERR_SEGREGATION_OF_DUTIES`), so sentence order was swapped — `app.py:857-861`.
- §3.8 Delinquency — insert — ambiguity — Pinned that only bills with a strictly positive unpaid remainder participate; "past due_date" is strict (`clock > due`) while the delinquent boundary at due+30d is inclusive, so a bill exactly on its `due_date` is neither past-due nor delinquent — `calc.py:156-179` (`account_delinquency`).

**Notes on things deliberately left unchanged:** The §3.5/§3.6 check orderings for bill issuance (INVALID_STATE→MISMATCH→PERIOD→OVERLAP) and payment (BILL_NOT_PAYABLE→MISMATCH→OVERPAYMENT) already match impl under the canonical §2.8 category order (state → referential-integrity → temporal/fiscal), so no edit was needed there. All endpoint role sets, response field shapes, ERU/fee formulas, state transitions, and the version/derived-field reconciliation rules were verified to already be uniquely pinned by the finalized PRD.

## Pipeline complete — 2026-07-10T13:20:43.395Z

Final state: 65/65 tests pass on all 8 sweep rounds. Artifacts: SCAFFOLD.yaml + 2 design indices, workspace/{INSTRUCTION,PRD,PRD_FINALIZED,PRD_COMPLETED}.md, workspace/implementation/ (38 routes), test_helpers/ (9 files), test_suite/ (conftest + 9 files, 65 tests). `sweep.sh` (orchestrator-authored 2×4-wave stability sweep) retained at task root.
