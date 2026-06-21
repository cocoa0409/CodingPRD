# Worklog — task_0423_equipment_finance_leasing

## Step 1: Create Task Directory — 2026-06-19T00:00:00.000Z

Created `tasks/task_0423_equipment_finance_leasing/` and `tasks/task_0423_equipment_finance_leasing/workspace/`. Pre-assigned task directory used verbatim (no index scan/auto-increment).

## Step 2: Generate Scaffold — 2026-06-19T00:00:00.000Z

All three scaffold artifacts are written and validated. Built fresh from the scenario and the scaffold-generator skill (no sibling tasks consulted).

**Files written (all 3):**
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, §1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, §1.9)

**Counts:**
- **Entities: 13** — Lessor, Vendor, CreditApplication, Lessee, Lease, EquipmentUnit, ScheduleLine, Invoice, Payment, UccFiling, TaxAssessment, AddOn, EndOfTermElection
- **Endpoints: 62** (34 POST actions + 28 GET, including FK reverse-reachability reads)
- **Errors: 27**
- **State machines: 8** — CreditApplication (cyclic revision loop), Vendor, Lease (parallel lifecycle × funding dimensions), EquipmentUnit (branching remarketing), Invoice, UccFiling (temporal coverage/lapse), EndOfTermElection (branching), AddOn (branching + cascade)
- **Roles: 4** — CreditAnalyst, FundingOfficer, Servicer, AssetManager (segregation-of-duties model)
- Plus 12 calculations, 26 validations, 1 concurrency rule (OCC on `Lease.version`)

**Difficulty band (§0.4 Expert):** Lands squarely in Expert — 13 entities (10–15), 62 endpoints, 27 errors (18–30), 4 roles (≥3), 8 state machines including cyclic, parallel-dimension, branching, and temporal-window machines.

**§1.8 / §1.9:** 9 difficulty rules × 2 = 18 difficulty instances; 47 corner instances (33 active + 14 `excluded_because` stubs).

**Validation:** `scaffold_lint.py` returns `VERDICT: clean lint`. All self-checks pass.

## Step 3: Copy Shared Files — 2026-06-19T00:00:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-19T00:00:00.000Z

Generated `workspace/PRD.md` — 303 lines — from the Equipment Finance & Leasing (Lessor) scaffold.

**Major sections produced:**
- §1 Introduction — segregation of duties, parallel lifecycle/funding state dimensions.
- §2 Global Specifications (11 subsections): RBAC (4 roles), API Response Structure (verbatim block), Pagination, Common Resource Properties, Hierarchical Consistency/Cascades, Nested Resource Retrieval, Monetary Values & Rounding, Logical Clock, OCC on Booking, Segregation of Duties, Validation Ordering.
- §3 Business Logic (12 subsections): Lessors/Vendors, Credit Application lifecycle, Lessee credit envelope, Lease origination & booking, Equipment & serial discipline, Pricing by product type (FMV/DOLLAR_OUT/TRAC), Funding/UCC/activation, Tax administration, Billing/payments, Add-ons/upgrades, End-of-term election/exercise/termination, Remarketing.
- §4 Endpoint Definitions — 62 endpoints.
- §5 Error Code Catalogue — 27 error codes.

**Hard Contract reports:** Field coverage PASS (72/72), Rule coverage PASS, Path purity PASS (§3 only). Neither withheld design file was read (appeared only in directory listing).


## Step 5: Generate Unit Tests — 2026-06-20T00:00:00.000Z

Generated complete test infrastructure for `task_0423_equipment_finance_leasing` from the two design indices only (no freelance walking of SCAFFOLD.yaml).

### Stage 1 — `test_helpers/` (9 files, all compile)
- **types.py** — 14 status enums, `UserRole`, and TypedDicts for all 14 entities (all carry `id/created_at/updated_at/version` per PRD §2.4, which states there are no append-only sub-resources).
- **api_errors.py** — all 27 `ERR_*` ids + HTTP status map, registered via `set_error_http_status_map`.
- **api_client.py** — one method per endpoint, rooted at `/lessors/{lessorId}`.
- **factories.py / constants.py / assertions.py / test_users.py** — PRD-exact field names; opaque-identity role headers with distinct analyst-1/analyst-2 for the segregation-of-duties rule.
- **fixtures.py** — composite helpers (approved lessee, booked/active/end-of-term lease, bill-and-pay-all-installments, returned/listed unit, etc.) consumed across both queues.

### Stage 2 — `test_suite/` (conftest + 6 files, 67 tests)
- **Difficulty queue (A):** 17 of 18 instances covered by exactly 2 tests each.
- **Corner queue (B):** all 33 non-stub instances covered by ≥1 test; all 14 `excluded_because:` stubs left untranslated (their 14 `difficulty_instance` pointers verified to resolve).
- Every test carries exactly one verbatim `Design:` tag; all 67 tags resolve to real, correctly-sectioned, non-stub instances. Every quoted PRD sentence was confirmed to survive a literal grep of PRD.md (C1). Zero `skip`/`skipif`/`xfail`.

### One instance deliberately skipped (gap left as gap)
`Difficulty/combinatorial_formula/buyout_quote_multibranch_three_inputs` asserts an FMV BUYOUT quote with a **non-zero remaining-rent term** (e.g., 930000). Per PRD §3.11 an end-of-term election is recorded only "within end-of-term," reachable only once `paid_installment_count >= term_months - advance_payment_count`, at which point the remaining-installment count floors to 0. The remaining-rent term is therefore structurally always 0 at any legitimately-reached BUYOUT election, so a faithful PRD-only implementer would never produce the multibranch value the instance pins — it fails the unique-derivability filter. Skipped (documented in `test_01_lease_pricing_variants.py`), with a second test added to the reachable sibling instance `invoice_sales_tax_round_per_line_order` so the `combinatorial_formula` rule retains 2 tests on its derivable instance.

Note: the framework (`prd_bench_local_runner`) is not installed in this environment, so files were validated by `py_compile` + static import/tag/citation audits rather than live pytest; the runner supplies the framework and `API_BASE_URL` at execution time.

## Step 6: Generate Implementation — 2026-06-20T00:00:00.000Z

Generated a complete Python + Flask implementation of the Equipment Finance & Leasing API at `workspace/implementation/`.

### Result
**67/67 tests pass** under genuine `--isolation per-test-server` (the runner's pytest plugin restarting the server before every test). Verified twice end-to-end at 39.9s, plus 67/67 against a stable server in 0.5s.

### Architecture
- `start.sh` — foreground launcher; guarded dep-install with a `.deps_ok` sentinel so steady-state reboots spawn exactly one Python process (avoids the per-test-reboot contention that causes flaky "could not be restarted" timeouts); `exec`s the server bound to `0.0.0.0:$PORT` (default 10000) via waitress (falls back to Flask dev server).
- `app.py` / `response.py` / `errors.py` / `middleware.py` / `db.py` — envelope (`meta`/`response_type`/`data`), error catalog (27 IDs with exact HTTP codes), `X-User-ID`/`X-User-Role` auth, in-memory store (no seeding — starts empty every boot).
- `routes/` (11 files) — all 62 endpoints across 13 entities.
- `services/` — `calculations.py` (Decimal + ROUND_HALF_UP for all bps math), `domain.py` (cascades, lookups, logical-clock temporal logic), `common.py` (validation/pagination/month arithmetic).

### Key correctness points implemented
- Parallel lease dimensions (lifecycle × funding) with auto BOOKED→ACTIVE on fund; depth-3 funding cascade (UCC auto-file + SALES_USE tax + activate).
- Dual-variant residual/buyout by lease type (FMV tiered bands, DOLLAR_OUT nominal 100, TRAC stipulated + floor).
- Credit/portfolio cascades; segregation of duties; pricing tiers; credit-score floor (580 inclusive).
- Half-open UCC coverage windows with lapse projected from the logical clock (reversible on clock movement); closed serial-reuse buffer `[D, D+30d]`.
- Straight-line depreciation floored at 20%; per-invoice round-then-tax; add-on incremental zero-on-empty-remaining.

### One bug found and fixed
`POST /leases/{id}/book` initially checked the from-state before the OCC version check, so a re-book with a stale version returned `ERR_INVALID_STATE` instead of `ERR_STALE_VERSION`. PRD §3.4 pins the version check first among booking preconditions — reordered so OCC precedes the state check.

### Note on the full-runner runs
The standalone `prd-bench-local-run` invocations I launched showed every test erroring on setup-timeout. Root cause was **concurrent-system contention** (4+ other `prd-bench-entrance` sessions and an 8-round sweep saturating CPU so the ~0.5s server reboot ballooned past the per-test timeout) — not a code defect. Isolated reproductions of the exact plugin restart path (correct `API_BASE_URL`, dnsboot injection, `start_new_session=True`) pass 67/67 cleanly.

## Step 7: Run Tests and Iterate — 2026-06-20T00:00:00.000Z

Definitive: all 8 parallel rounds passed cleanly. Every round reports `total=67, passed=67, failed=0, errors=0, skipped=0`, and the per-test `status` field is `"passed"` for all 67 tests in every round, with zero non-passed entries. (The "fails" list in the first diagnostic pass was an artifact of reading the wrong key — `outcome` instead of `status` — and is not a real signal.)

The exit condition is met: all 8 rounds have `passed == total`. No tests needed deletion, and no fixes to `test_helpers/` or `implementation/` were required.

**Iterations run:** 1 (the initial 8-round parallel sweep passed clean on the first attempt — no fix loop needed).

**Result:** All 8 concurrent rounds passed with 67/67 tests (`passed == total`, 0 failed / 0 errored / 0 skipped in every round). Verified against the authoritative top-level counters and confirmed per-test via the `status` field (all 67 = `"passed"`, every round). No flakiness surfaced across the parallel sweep — every round was identical.

**Tests deleted:** None. No test failed unique-derivability or PRD-coverage checks because no test failed at all.

**Fixes applied to `test_helpers/`:** None required.

**Fixes applied to `implementation/`:** None required.

Orchestrator independently re-verified all 8 `results.{1..8}.json`: each reports total=67 passed=67 failed=0 errors=0 skipped=0.

## Step 8: Finalize PRD — SKIPPED — 2026-06-20T00:00:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits, so PRD_FINALIZED.md is not produced. (Step 6's own generation-time bug fix — book-endpoint OCC ordering — was internal to Step 6, not a Step 7 signal, and does not affect the skip condition.)

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-06-20T00:00:00.000Z

**File:** `workspace/PRD_COMPLETED.md` (created via `cp PRD.md PRD_COMPLETED.md`, then edited — PRD_FINALIZED.md absent since Step 8 skipped)

**Line counts:** PRD.md = 303 lines, PRD_COMPLETED.md = 303 lines (all changes in-paragraph; no lines added/removed)
**Char delta:** 46,754 → 49,980 chars (+3,226)

**Counts:** 11 total changes — 10 ambiguity-pins, 1 mismatch-revision

**Per-change:**
- §2.3 Pagination — insert — ambiguity — out-of-range/unparseable `limit`/`offset` → `ERR_INVALID_REQUEST` (not clamped); `created_at` ties broken by insertion order; `has_more` formula; undocumented exact-match `status` filter on every status-bearing list endpoint plus `tax_type` on tax list — `services/common.py:53-65,68-70`, `routes/vendors.py:52-54`, `routes/tax.py:70-73`, `response.py:50`
- §2.8 Logical Clock — insert — ambiguity — initial `clock_utc` = server wall-clock at creation (ISO 8601, 3 fractional digits); `to_iso8601` parsing (Z/offset/naive-UTC), may move backward; missing/unparseable → `ERR_INVALID_REQUEST` — `routes/lessors.py:34,56-58`, `services/common.py:143-161`
- §3.2 Credit Application (creation) — insert — ambiguity — unset `approved_amount_cents`/`pricing_tier`/`submitted_by_user_id` are `null`; `requested_amount_cents` positive-int and `credit_score` int validated at creation → `ERR_INVALID_REQUEST` — `routes/credit_applications.py:30-31,37-40`
- §3.2 Credit Application (approve) — revise — mismatch — PRD bundled "`approved_amount_cents` > 0" under `ERR_APPROVED_EXCEEDS_REQUESTED`; impl validates positivity as a priority-4 body check → `ERR_INVALID_REQUEST` (ahead of state/business rules), reserving `ERR_APPROVED_EXCEEDS_REQUESTED` for the exceeds-requested case only — `routes/credit_applications.py:131,138-140`
- §3.4 Originating a Lease — insert — ambiguity — `vendor_id` recorded as non-empty string, existence/approval deferred to funding; computed fields begin at integer `0`, `booked_clock_utc`/omitted `trac_residual_pct_bps` begin `null` — `routes/leases.py:35,40,55-62`, `routes/leases.py:191-193`
- §3.7 Funding (auto UCC) — insert — ambiguity — auto-filed UCC `jurisdiction_state_code` = lessor `home_state_code` — `routes/leases.py:204`
- §3.7 Manual UCC filing — insert — ambiguity — overlap check evaluated before jurisdiction check — `routes/ucc.py:39-51`
- §3.9 Payments — insert — ambiguity — `amount_cents` positive-int → `ERR_INVALID_REQUEST`; target invoice must be `OPEN` else `ERR_INVALID_STATE` — `routes/billing.py:153-156`
- §3.10 Add-On apply — insert — ambiguity — serial discipline checked after the three apply gates; new unit `original_cost_cents` = `added_cost_cents`; UPGRADE replaced unit also gets `disposed_clock_utc` = current clock (starts buffer) — `routes/add_ons.py:114-128,153,162-163`
- §3.11 RENEW exercise — insert — ambiguity — appended schedule lines: consecutive `installment_number` after term, `is_advance` false, status `SCHEDULED`, `base_rent_cents` = `monthly_payment_cents`, `due_clock_utc` = `booked_clock_utc` + n months — `routes/eot_elections.py:116-134`
- §3.12 Remarketing (disposal) — revise — mismatch — `disposed_clock_utc` enumeration extended to include the UPGRADE-replaced-unit path (PRD listed only `RETURNED`/`LISTED`) — `routes/add_ons.py:162-163`

**Deliberately left unchanged (judgment calls):** impl's internal-only `deposit_refundable` (lease) and `remarketing_gain_loss_cents` (equipment) fields are absent from `test_helpers/types.py` and asserted by no test, so PRD's generic prose was kept rather than pinning out-of-contract field names; `filing_number` format string left unpinned (opaque, non-load-bearing).

---

## Pipeline complete — 2026-06-20T00:00:00.000Z

All steps done. task_0423_equipment_finance_leasing: 67/67 tests pass across all 8 stability-sweep rounds. Artifacts: SCAFFOLD trio, PRD.md, PRD_COMPLETED.md, test_helpers/, test_suite/ (67 tests), workspace/implementation/ (Python+Flask, in-memory). Step 8 skipped (Step 7 clean on first sweep).
