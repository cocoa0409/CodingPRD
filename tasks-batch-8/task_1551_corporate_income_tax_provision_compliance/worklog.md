# Worklog — task_1551_corporate_income_tax_provision_compliance

## Step 1: Create Task Directory — 2026-08-13T20:31:00.000Z

Pre-assigned directory `tasks/task_1551_corporate_income_tax_provision_compliance/` with `workspace/` already created by the pipeline launcher. No index scan performed; treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-13T21:10:00.000Z

Scaffold generation complete and clean. Summary of what was produced for `task_1551_corporate_income_tax_provision_compliance`:

## Design

**Complexity profile**: primary archetype `compliance_audit` + secondary `ledger_reconciliation`; layers: dual-variant calculation, rate/threshold triggers, derived-field reconciliation, optimistic concurrency; flat topology (peer entities, FK links, prioritized per §0.3); cyclic state-machine shape; segregation-of-duties role model; immediate consistency.

**Core mechanics**:
- Book-to-tax differences (IDENTIFIED→REVIEWED→LOCKED/REJECTED with a rework cycle) cascade on lock into DeferredTaxItem rollforward lines → TaxYear deferred/ETR recompute (depth-3 cascade)
- Valuation allowance with nested min/max measurement, mltn conditional branch, OCC-guarded create-with-supersede, and SoD-gated approval
- UTP recognition at the strict `> 5000 bp` threshold with interest accrual, cross-aggregate disclosure gate on the jurisdiction's Filing, and clock-driven statute lapse
- Estimated payments: dual-variant scheduling (safe-harbor vs annualized), pinned per-quarter cumulative rounding, LATE sweep + one-time penalty, record/reverse compensation
- Filings with parallel `status × extension_status` dimensions, OCC-gated file, RTP true-up cascade that re-spreads remaining annualized quarters
- Notices (auto-OVERDUE sweep) gating audit closure; audits with a negotiate/revise cycle and half-open exam-period overlap rule (contrasted with payments' closed-interval rule)

## Counts

| Element | Count |
|---|---|
| Entities | 10 |
| State machines | 8 (3 cyclic, 1 parallel-dimension) |
| Calculations | 9 (2 dual-variant, 3 combinatorial modes a/b/c) |
| Endpoints | 58 (all exercised in ≥1 recipe) |
| Roles | 5 (all `opaque`: TaxAccountant, TaxManager, TaxDirector, Auditor, PlatformAdmin) |
| Errors | 26 (all referenced by tests) |
| Validations | 11 ordered priorities; 2 OCC concurrency rules |
| **§1.8 difficulty instances (non-stub)** | **18** (9 rules × 2) |
| **§1.9 corner instances (non-stub)** | **44** (+9 excluded-because stubs) |

All 528 `setup_api_calls`/`trigger` calls across both design files pass `scaffold_lint.py` with verdict `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Every formula-derived assert literal was computed by executing the pinned formula (two initial slips — a −63 bp ETR and 567,767-cent re-spread — were caught by that verification and fixed). No forbidden concurrency vocabulary; enum values all reachable; no sibling task was read at any point.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1551_corporate_income_tax_provision_compliance/SCAFFOLD.yaml` (§1.0–§1.7 only — no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1551_corporate_income_tax_provision_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1551_corporate_income_tax_provision_compliance/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

## Step 3: Copy Shared Files — 2026-08-13T21:26:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1551_corporate_income_tax_provision_compliance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T21:35:00.000Z

PRD generated and all three hard contracts verified. The earlier zero-count was an artifact of my audit script's section-split logic; the explicit-heading re-check confirms 461 §3 backtick tokens with zero path/method violations.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1551_corporate_income_tax_provision_compliance/workspace/PRD.md`

**Line count:** 312 lines
**Sections:** §1 Introduction (2 paragraphs), §2 with 10 subsections (2.1–2.10, domain-titled: Resource Identity, Precision/Rounding, Validation Priority, Logical Clock & Sweeps, OCC, Interval Semantics, Cascades/Freezing), §3 with 9 subsections (lifecycle-grouped: year setup → differences/deferred rollforward → valuation allowance → UTPs → estimated payments → tax stack/ETR → filings/extensions/RTP → year close → notices/audits), §4 endpoint table, §5 error catalogue.

**Coverage-audit notes:**

- **Contract 1 (Field-Name Coverage):** all 10 entities' fields + every endpoint `input` identifier + common fields (`id`, `created_at`, `updated_at`, `version`) + pagination fields (`limit`, `offset`, `total_count`, `has_more`) — 90 required, 90 present, 0 missing. **PASS**
- **Contract 2 (Rule Coverage):** manually walked — validation priority order (11 levels) rendered as an explicit ordered list in §2.6; both `concurrency_rules` entries (VA create + filing file) expressed in §2.8 with `expected_tax_year_version`, `ERR_STALE_VERSION`, HTTP 412; all 42 state-machine transitions across 8 entities rendered in §3 with preconditions paired to error IDs; all 8 calculations (`difference_amount`, `deferred_tax_movement`, `valuation_allowance_measurement`, `utp_recognition_measurement` incl. strict >5000 threshold and 500 bp interest, `etr_calculation` both variants, `estimated_payment_schedule` incl. pinned per-quarter cumulative rounding, `current_tax_stack` incl. pinned 5-step order and 10^8 divisor, `underpayment_penalty` at 400 bp, `rtp_trueup` incl. last-quarter remainder absorption and from-base idempotency) expressed in prose with no pseudocode; all 26 error IDs appear in §2/§3 narrative, not just §5; sibling branches (payment record/reverse state pairs, extension PENDING/READY pairs, close outcomes) given symmetric density. **PASS**
- **Contract 3 (§3 Path Purity):** 461 backtick tokens in §3 scanned; 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path combos. Endpoints referenced via state-transition framing and role+verb. **PASS**
- §2.2 emitted verbatim from the canonical block; §4 table has 58 rows (matches scaffold's 58 endpoints) with only Method/Path/Description/Roles columns; §5 table has all 26 errors with only Error ID / HTTP Status columns.
- The forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T22:40:00.000Z

All done. Final summary:

## Summary

**Tests emitted — 80 total, zero skipped:**

- **Queue A (Difficulty): 36 tests** — all 18 instances × 2 tests each, every one carrying its `Design: Difficulty/<rule_id>/<instance.name>` tag.
- **Queue B (Corner): 44 tests** — all 44 non-stub instances × 1 test each with `Design: Corner/<section>/<instance.name>`. All 9 `excluded_because:` stubs left untranslated; their difficulty-instance cross-references all resolve.

**Instances skipped: 0.** Every instance passed the PRD-first two-condition filter. Two local adjudications worth noting:
- **Absolute `version` values** (`version == 1`, `version == 3/5`) are not uniquely derivable — PRD §2.4 says only "starts at its initial value and increments on mutation" — so those sub-assertions were translated as monotonic-increment checks rather than hard-coded absolute numbers. The instances themselves were still fully translated.
- **`etr_forecast_vs_actual_divergence` setup-chain repair:** the recipe never discloses UTP2 (liability 1,000,000 → `disclosure_required == true`) before filing FED, which the PRD's file gate (`ERR_UTP_UNDISCLOSED`) would reject. The fixture inserts the PRD-mandated `disclose` call (which leaves all asserted figures unchanged — DISCLOSED positions stay in the reserve).

**test_helpers/ written** (9 files): `types.py` (10 entity TypedDicts + 13 enums, all common-fields-carrying), `api_client.py` (44 endpoint methods), `api_errors.py` (26 error IDs registered with the framework's status map), `assertions.py` (10 entity assertions + rollforward invariant), `factories.py` (10 payload factories), `constants.py` (PRD-named thresholds: 5000 bp recognition, 500 bp interest, 400 bp penalty, 3-year statute), `test_users.py` (5 opaque-role header constants + per-user builders for segregation-of-duties), `fixtures.py` (7 tiers incl. `setup_locked_year_with_filing`, `setup_year_with_annualized_schedule`, `setup_dual_variant_etr_scenario`, `setup_rtp_respread_scenario` with fresh OCC version reads before every version-carrying write), `__init__.py` barrel.

**test_suite/ written** (9 files): `conftest.py` + 8 numbered test files (year setup/access/envelope, differences & deferred rollforward, valuation allowances, UTPs, estimated payments, filings/extensions/RTP, provision lifecycle & ETR, notices & audits).

**Self-checks (all PASS):**
- Coverage audit: 18/18 difficulty instances at ≥2 tests; 44/44 non-stub corner instances at ≥1 test; 9/9 stubs untranslated with resolved cross-refs; no tags pointing at non-existent instances.
- Every docstring ends with exactly one Design tag (checked all 80).
- PRD citation verbatim grep: 115 long quote spans checked against PRD.md, 0 misses.
- No `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold"/table references in generated comments; pyflakes clean; `pytest --collect-only` collects 80 tests with runner-style `PYTHONPATH`.

All asserted figures were re-verified against the PRD's pinned formulas (current_provision 23,200,818; forecast ETR 2389 / actual 2279; RTP −100,818; IL quarters 552,537/552,538/552,537/552,537 summing to 2,210,149; safe-harbor 500,600; VA 320,000 vs 630,000; penalties 40 and 2,101; re-spread 567,767/567,767/567,766 summing exactly to the 45,800 delta).

## Step 6: Generate Implementation — 2026-08-13T22:40:00.000Z

Implementation complete and green: `prd-bench-local-run --isolation per-test-server` → **80/80 passed, 0 failed, 0 errors**, twice consecutively (the second run after the UTP pre-measure default hardening), the first run landing while an 8-round concurrent sweep from a sibling task occupied the host.

### File list
`/home/ubuntu/github/CodingPRD/tasks/task_1551_corporate_income_tax_provision_compliance/workspace/implementation/`
- `start.sh` — guarded launcher (`pip install` only if flask missing; `exec python3 app.py`; `0.0.0.0:$PORT`)
- `requirements.txt`, `app.py` (app factory, envelope-shaped 404/405/500 handlers, blueprint registration)
- `db.py` (in-memory store, 10 collections, empty at boot; `touch` vs `touch_year`/`bump_year` so TaxYear.version moves only on declared side effects), `errors.py` (all 26 error IDs with exact HTTP statuses), `response.py` (`meta`/`response_type`/`data` envelope, pagination meta), `util.py` (UUIDs, 3-fractional-digit wall-clock timestamps, logical clock defaulting to 2026-08-01T00:00:00Z, calendrical `add_months`/`add_years`/`whole_months`, exact-integer `round_half_up_int`), `validate.py` (defensive body reads + priority-11 structural validators), `middleware.py` (auth priorities 1–2: `X-User-ID`/`X-User-Role`, five declared roles), `serializers.py` (UTP interest recomputed on every read)
- `routes/`: clock, tax_years, jurisdictions, differences, deferred_items, valuation_allowances, utps, payments, filings, notices, audits + `common.py` (filters, pagination)
- `services/`: `calc.py` (all §1.3 calculations + TaxYear derived-field recomputes + RTP re-spread), `sweeps.py` (late/overdue/lapse sweeps run synchronously inside the clock-set request)

### Verification
- Two full `per-test-server` runs: 80/80 each (108s / 111s; ~0.7s per boot).
- A ~130-assertion smoke suite replayed the design indices' pinned numbers before the harness runs: tax stack 23,200,818 (CA 2,254,200 then FED 20,946,618 — pinned order), forecast 2389 vs actual 2279 bp, RTP −100,818, IL cumulative rounding 552537/552538/552537/552537 vs NY safe-harbor 500600, re-spread 567767/567767/567766 from base with PAID q1 untouched, penalty 2,101 kept through payoff, interest 16,667 (4 whole months floored), statute lapse at filed_on+3y, OCC 412 on both anchored writes, closed-vs-half-open interval rules, SoD 403, supersede chains, record/reverse conservation.

### PRD interpretation decisions (underdetermined points)
- **Logical clock is freely settable**, including backwards relative to the 2026-08-01 default — every design fixture's first call sets 2026-01-05, so regression rejection would fail the suite; only malformed `to_iso8601` is 400.
- **TaxYear.version increments exactly on the ten declared side effects** (lock-provision, mark-returns-filed, close, VA create/approve, UTP measure/settle/lapse, filing file/reject) — not on derived-field recomputes such as the difference-lock cascade (scaffold lists the increment explicitly per transition; the OCC anchors depend on it).
- **Partial record-payment on a LATE quarter** → `ERR_INVALID_STATE_TRANSITION` (the only declared LATE record-payment transition is exact completion; PRD §3.5 describes partial payments only for SCHEDULED/PARTIALLY_PAID). Partial on PARTIALLY_PAID accrues and stays PARTIALLY_PAID.
- **UTP creation on a CLOSED year** → `ERR_TAX_YEAR_NOT_OPEN` (409); UTP creation is admitted in OPEN/PROVISION_LOCKED/RETURNS_FILED per PRD §3.4.
- **Year-close readiness breaches** (open audits or unresolved tied notices) → `ERR_UNRESOLVED_NOTICES` (422) — the catalog declares no audit-specific year-close error.
- **AGREED close with missing `agreed_adjustment_cents`** → 400 `ERR_INVALID_REQUEST` (conditionally required field); negative → 422 `ERR_INVALID_AMOUNT`. `proposed_adjustment_cents` negative → 422.
- **Pagination clamps** (limit to 1..100, offset to ≥0; unparseable falls back to defaults) — no pagination error exists in the catalog.
- **Multiple FEDERAL jurisdictions with filings**: one federal component is computed once for `current_provision_cents`; every FEDERAL jurisdiction's filings receive it as their `estimated_liability_cents`.
- **UTP lapse** uses the latest `filed_on` among FILED/ACCEPTED filings sharing (tax_year_id, jurisdiction_id).
- **Pre-measure UTP shape**: `recognized_benefit_cents`/`liability_cents` are 0 (the test-helpers' shape assertion requires ints); `cumulative_probability_bp`/`measured_on` null until first measure.
- **`rejection_reason`** required non-empty at structural priority; stored but not serialized (not a declared Filing field).

## Step 7: Run Tests and Iterate — 2026-08-13T22:49:08.303Z

All 8 rounds passed 80/80 — the exit condition is met on the first sweep.

**Summary**

- **Iterations run:** 1 (single 8-round parallel stability sweep; all 8 rounds completed to termination).
- **Results:** rounds 1–8 each `passed=80 total=80 failed=0 errors=0`. Zero flakiness surfaced across the concurrent sweep.
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

The task's existing artifacts (implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1551_corporate_income_tax_provision_compliance/workspace/implementation/` and test suite at `/home/ubuntu/github/CodingPRD/tasks/task_1551_corporate_income_tax_provision_compliance/test_suite/`) were already green from the prior pipeline steps recorded in `worklog.md`, and the 8-round concurrent sweep confirmed stability under parallel load — no timing-sensitive failures, port collisions, or fixture-ordering issues emerged. No changes were required.

## Step 8: Finalize PRD — 2026-08-13T22:49:08.303Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced.

## Step 9: Complete PRD — 2026-08-13T23:07:36.702Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1551_corporate_income_tax_provision_compliance/workspace/PRD_COMPLETED.md` written (no PRD_FINALIZED.md existed, so sourced from PRD.md).

**Size:** 311 → 311 lines (all edits in-paragraph, no new sections); 48756 → 53361 chars (**+4605**).

**Counts:** 25 ambiguity-pins, 2 mismatch-revisions (27 edit hunks total; one hunk carries both a mismatch-revision and pins).

Per-change bullets:

- §2.1 — insert — ambiguity — empty/whitespace-only `X-User-ID`/`X-User-Role` count as missing — implementation/middleware.py:30-32
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped, unparseable values fall back to defaults; `has_more` = offset + returned items < total_count; created_at ties keep creation order — implementation/routes/common.py:24-40, implementation/response.py:28
- §2.4 — revise — ambiguity — `version` starts at 1 (was "starts at its initial value") — implementation/db.py:35
- §2.4 — insert — ambiguity — calendrical arithmetic pinned: month-add clamps day to month length; year-add maps Feb 29 → Feb 28 in non-leap years — implementation/util.py:106-119
- §2.6 item 5 — revise — ambiguity — "PROVISION_LOCKED or later" pinned to exactly PROVISION_LOCKED or RETURNS_FILED, never CLOSED — implementation/routes/filings.py:159, 120-121
- §2.6 item 10 — revise — ambiguity — amount sanity covers positive *or nonnegative* inputs (settlements, adjustments, scheduled amounts admit zero) — implementation/routes/payments.py:175-177, implementation/routes/utps.py:176-178, implementation/routes/audits.py:113-115
- §2.7 — insert — ambiguity — clock settable to any well-formed instant including backwards; missing/malformed `to_iso8601` is ERR_INVALID_REQUEST; created_at/updated_at/api_request_timestamp stay wall-clock; sweep id lists in creation order — implementation/routes/clock.py:19-22, implementation/util.py:26-29,67-78, implementation/services/sweeps.py:20-53
- §2.7 — insert — ambiguity — UTP lapse uses the latest `filed_on` when several FILED/ACCEPTED filings share the pair — implementation/services/sweeps.py:49-50
- §2.8 — insert — ambiguity — stale-version check evaluates immediately after tax-year posture (item 5), before deadline/cross-entity/amount/structural checks; missing or non-integer `expected_tax_year_version` is structural ERR_INVALID_REQUEST — implementation/routes/valuation_allowances.py:52-56,70, implementation/routes/filings.py:165-169,189
- §2.9 — insert — ambiguity — creating the pair's first quarter with quarter_index > 1 is ERR_QUARTER_GAP — implementation/routes/payments.py:153-156
- §3.1 — revise — **mismatch** — dropped "unique" from `fiscal_year_label`; no uniqueness check exists — implementation/routes/tax_years.py:53-58
- §3.1 — insert — ambiguity — out-of-range jurisdiction rate/month/day values are structural ERR_INVALID_REQUEST — implementation/routes/jurisdictions.py:39-46
- §3.3 — insert — ambiguity — negative `projected_taxable_income_cents`/`reversing_dtl_cents` is ERR_INVALID_AMOUNT — implementation/routes/valuation_allowances.py:58-62
- §3.3 — revise — ambiguity — "no other precondition" on return pinned to mean nothing beyond the §2.6 item-5 OPEN posture — implementation/routes/valuation_allowances.py:118-126,166-172
- §3.4 — insert — ambiguity — UTP identification in a CLOSED year is ERR_TAX_YEAR_NOT_OPEN; new position's initial measurement fields (recognized/liability 0, disclosure_required false, interest 0, probability/measured_on/settled null) — implementation/routes/utps.py:50-53,74-81
- §3.4 — insert — ambiguity — whole-month interest counted by monthly anniversary day; zero before first measurement or at zero liability; accrual unchanged after settle/lapse (liability_cents never cleared) — implementation/services/calc.py:93-106, implementation/util.py:122-127
- §3.4 — insert — ambiguity — negative `settled_amount_cents` is ERR_INVALID_AMOUNT — implementation/routes/utps.py:176-178
- §3.5 — insert — ambiguity — generate-schedule returns HTTP 201, `response_type` "array", four payments ascending quarter_index, no pagination fields in meta — implementation/routes/payments.py:107-115
- §3.5 — revise — **mismatch** — manual-quarter `due_date` rule: only a due_date earlier than period_start_date is ERR_DATE_RANGE_INVALID; due_date after period_end is permitted (PRD said "outside the quarter interval"); same edit pins quarter_index outside 1–4 → ERR_INVALID_REQUEST and negative scheduled_amount_cents → ERR_INVALID_AMOUNT — implementation/routes/payments.py:165-177,184-186
- §3.5 — insert — ambiguity — partial payment keeps PARTIALLY_PAID; from LATE only exact completion is accepted, smaller payment is ERR_INVALID_STATE_TRANSITION — implementation/routes/payments.py:258-266
- §3.5 — insert — ambiguity — reversal from SCHEDULED is ERR_INVALID_STATE_TRANSITION; reversal from LATE leaving positive balance moves to PARTIALLY_PAID — implementation/routes/payments.py:277-280,305-309
- §3.6 — insert — ambiguity — federal component attributed to every FEDERAL jurisdiction holding a filing (drives lock-provision stamping) — implementation/services/calc.py:141-144
- §3.7 — insert — ambiguity — multiple filings per (year, jurisdiction) pair allowed; new filing starts with return_tax_liability_cents null and is_late false — implementation/routes/filings.py:71-82
- §3.7 — insert — ambiguity — `rejection_reason` must be a non-empty string (ERR_INVALID_REQUEST) — implementation/routes/filings.py:226
- §3.8 — insert — ambiguity — year-close precondition breaches (unclosed audits or unresolved tied notices) are ERR_UNRESOLVED_NOTICES — implementation/routes/tax_years.py:146-159
- §3.9 — insert — ambiguity — closing an already-closed audit or an outcome with no declared transition from current state is ERR_INVALID_STATE_TRANSITION; negative proposed/agreed adjustment is ERR_INVALID_AMOUNT — implementation/routes/audits.py:155-165,113-115,174-176
- §4 — insert — ambiguity — per-endpoint exact-match filter inventory for all list endpoints; undeclared path or unsupported method returns ERR_NOT_FOUND (404) envelope — implementation/routes/common.py:14-21, implementation/app.py:31-37

Everything else in the implementation (state machines, calculation formulas and their rounding order, cascade hops, OCC semantics, sweep conditions, error catalogue, RBAC table) was already uniquely pinned by the PRD and left untouched.
