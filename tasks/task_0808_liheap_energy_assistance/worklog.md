# Worklog — task_0808_liheap_energy_assistance

## Step 1: Create task directory — 2026-07-09T00:00:00.000Z

Created `tasks/task_0808_liheap_energy_assistance/` and `tasks/task_0808_liheap_energy_assistance/workspace/` (pre-assigned directory, no index auto-scan).

## Step 2: Generate Scaffold — 2026-07-09T00:30:00.000Z

All checks pass. The scaffold is complete and lint-clean. Final summary:

## Generated: `task_0808_liheap_energy_assistance` (Expert)

Three files written to `/home/ubuntu/github/CodingPRD/tasks/task_0808_liheap_energy_assistance/`, all parsing under `yaml.safe_load` and passing `scaffold_lint.py` with **VERDICT: clean lint** (323 §1.8/§1.9 calls checked, all FK reverse-reachability satisfied).

**Complexity profile:** Quota/allocation primary (seasonal funding depletion) + Pricing-engine secondary (benefit tiers); flat topology; branching state machines; peer_roles; immediate consistency. Layers: rate_threshold_triggers, cascading_side_effects, dual_variant_calculation, optimistic_concurrency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **11 entities:** FundingPool, Household, Application, IncomeDocument, Vendor, UtilityAccount, Pledge, CrisisBenefit, Payment, BillCredit, WeatherizationReferral
- **8 state machines** — non-linear on Application (SUBMITTED→INFO_REQUESTED→SUBMITTED cycle + APPROVED/DENIED fork) and CrisisBenefit (OPEN→{RESOLVED, BREACHED}); plus FundingPool status-derivation, IncomeDocument, Vendor, Pledge, Payment (remit+compensating return), WeatherizationReferral
- **7 calculations:** income_eligibility (150% FPL threshold), benefit_tier_award (tiered, nonlinear min/max cap), benefit_component_rounding (round-then-sum, order pinned), crisis_benefit_amount (estimate vs resolved), pool_accounting (conservation invariant), bill_credit_allocation (arrearage-first waterfall + account-ledger invariant), referral_priority
- **21 validations** (priority-ordered, distinct categories) · **44 endpoints** (incl. `/_clock/set_current_utc` with default `2026-03-01T00:00:00Z`) · **22 errors** · **4 roles** (Applicant/VendorAgent entity-backed; Caseworker/ProgramAdmin opaque)
- **1 concurrency rule:** `pledge-create-stale-pool` (OCC on FundingPool.version, 412)

**§1.8 SCAFFOLD_DIFFICULTY_DESIGN.yaml:** 9 rule_ids × 2 = **18 instances**, all grounded in §1.1–§1.7, every formula-derived assert pre-computed to a literal (verified in Python: e.g. provisional benefit 112900 vs final 88200; cap 150000; rounding divergence 112900 vs 112800; crisis estimate 60000 vs resolved 45000; FPL boundary 150.00 eligible / 150.48 not).

**§1.9 SCAFFOLD_CORNER_DESIGN.yaml:** **25 active** corner instances + **6 excluded_because stubs** (citing §1.8 instances) — covering creation/not-found/required/computed fields, invalid-transition/idempotency/terminal-lockdown, every un-covered error trigger (INVALID_REFERENCE, POOL_COMPONENT_MISMATCH, ACCOUNT_NOT_DISCONNECTED, VENDOR_NOT_ENROLLED, BENEFIT_EXCEEDS_AVAILABLE, DUPLICATE_APPLICATION, INCOME_NOT_VERIFIED, CRISIS_DEADLINE_PASSED, CRISIS_NOT_DUE, PAYMENT_NOT_REMITTED), RBAC denials, OCC stale-version, pagination, and referral_priority.

**Note:** One design fix during authoring — the crisis 48-hour deadline uses an explicit `POST /crisis-benefits/{id}/breach` (guarded by clock ≥ resolve_by) rather than an auto-cascade on clock-set, so that both `ERR_CRISIS_DEADLINE_PASSED` (late resolve) and BREACHED (explicit) are independently reachable. 49 instance names total, all unique across both design files.

## Step 3: Copy Shared Files — 2026-07-09T00:31:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0808_liheap_energy_assistance/workspace/INSTRUCTION.md`.

---

**RESUME NOTE — 2026-07-10T03:19:54.000Z**: Pipeline was interrupted after Step 3 by an account weekly-limit kill ("You've hit your weekly limit"); the process died before Step 4 began. API availability re-probed (PROBE_OK). Resumed from Step 4. Steps 1–3 artifacts on disk were reused verbatim; `SCAFFOLD*.yaml` and `workspace/INSTRUCTION.md` were not regenerated or modified.

## Step 4: Generate PRD — 2026-07-10T03:19:54.000Z

All three hard contracts pass, and the endpoint table lists exactly 44 endpoints matching the scaffold (including `POST /_clock/set_current_utc`).

The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_0808_liheap_energy_assistance/workspace/PRD.md`.

## Summary

Generated a prose PRD for the LIHEAP Energy Assistance API (Expert task) from the scaffold, without opening either withheld design file.

**Structure:**
- §1 Introduction (3 paragraphs, framed around fiscal conservation + 48-hour crisis time-pressure + logical clock)
- §2 Global specs: RBAC with all four roles and their `entity_backed`/`opaque` identity semantics; §2.2 verbatim response envelope; pagination; common properties + logical clock (default `2026-03-01T00:00:00Z`); OCC on funding-pool version; monetary precision; pool ledger conservation invariant; account ledger invariant; validation ordering
- §3 Business logic in 9 scattered subsections: pool lifecycle/status derivation, household intake + application eligibility, income docs + info-request cycle, approval/benefit finalization/auto-referral (with the full income-eligibility, tiered-award, and round-then-sum component-rounding formulas rendered in prose), vendors/utility accounts, pledges, payments + bill-credit waterfall, crisis benefits + 48h deadline, referral priority
- §4 endpoint table (4 columns) and §5 error table (2 columns)

**Hard Contract audit results:**

```
Contract 1 — Field-Name Coverage: 65 required identifiers (entity fields + request/query/path params), 0 missing. Enum/state values: 0 missing. Error IDs: all 22 present. Status: PASS

Contract 2 — Rule Coverage: all state transitions (FundingPool derivation + close cascade, Application branching fork, IncomeDocument verify/reject, Vendor enroll, Pledge lifecycle + release, Payment remit/return cascade, CrisisBenefit resolve/breach, Referral schedule) expressed with preconditions paired to error_ids; all 7 calculations rendered precisely (income_eligibility FPL table, benefit_tier_award, pinned round-then-sum component rounding, crisis flat rates, pool_accounting invariant, arrearage-first bill_credit waterfall, referral_priority); OCC rule names write endpoint + expected_pool_version + ERR_STALE_POOL_VERSION/412; validation priority ordering stated in §2.9. Status: PASS

Contract 3 — §3 Path Purity: 398 backtick tokens scanned; 0 starting with `/`; 0 bare HTTP-method tokens; 0 method+path tokens. Status: PASS
```

**Endpoint coverage audit:** 44/44 scaffold endpoints appear in §4, verified programmatically — including `POST /_clock/set_current_utc`. All required constraints satisfied; PRD ends at §5 with no audit footer.

**Orchestrator verification (independent of subagent claim):** re-parsed `SCAFFOLD.yaml` and regex-matched every endpoint path against `PRD.md` — 44/44 present, 0 missing. All 22 `error_id` values present. Leakage sentinels (`test_recipe`, `scaffold_difficulty_design`, `scaffold_corner_design`, `Design:`) absent from PRD.md. PRD.md = 265 lines / 42009 bytes.

## Step 5: Generate Unit Tests — reconstructed from disk 2026-07-10T03:36:00.000Z

**NOTE — reconstructed record.** The `claude -p` process that ran Steps 5 and 6 exited silently (0 bytes of output) after Step 6 completed and before Step 7 started. The Step 5/6 subagent summaries were lost with that context and cannot be pasted verbatim. This entry is reconstructed by the resuming orchestrator from the on-disk artifacts, which were verified independently.

- `test_helpers/` — 9 modules: `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.
- `test_suite/` — `conftest.py` (34 lines) plus 4 test modules totalling **40 test functions**:
  - `test_01_eligibility_and_benefit.py` — 11 tests
  - `test_02_application_lifecycle.py` — 6 tests
  - `test_03_pledges_and_pool.py` — 18 tests
  - `test_04_payments_and_ledger.py` — 5 tests
- All 40 test functions carry a `Design:` tag (40 tags found). All files pass `ast.parse`.

## Step 6: Generate Implementation — reconstructed from disk 2026-07-10T03:36:00.000Z

**NOTE — reconstructed record, and Step 6 was INCOMPLETE on disk.** The Step 6 subagent died at a write boundary (a known failure mode): it wrote the store, calculation, shared-helper and 9 route modules, then exited before writing the application entrypoint and the final two route modules. The defect was invisible to Steps 1–6 validation because every file present did parse cleanly.

Present and correct after Step 6: `store.py`, `common.py`, `calc.py`, `helpers.py`, `pledge_ops.py`, and route modules `r_pools.py`, `r_households.py`, `r_applications.py`, `r_income.py`, `r_vendors.py`, `r_accounts.py`, `r_pledges.py`, `r_payments.py`, `r_billcredits.py`, plus `start.sh` and `requirements.txt`.

Missing after Step 6 (detected by the resuming orchestrator at Step 7):
1. **`app.py` — absent.** `start.sh` ends in `exec python3 app.py`, so every server boot died with `python3: can't open file '.../app.py'` → `ServerStartError: Server process exited prematurely with code 2`. No round could produce a `results.json`. This failure superficially resembles host saturation but is not: it reproduced deterministically at zero load.
2. **9 of 44 scaffold endpoints unrouted** — all of `crisis-benefits` (5) and `weatherization-referrals` (4). No `r_crisis.py`, no `r_referrals.py`.

Corroborating evidence that these were intended-but-unwritten, not designed-away: `store.py` already declared the `crisis_benefits` and `weatherization_referrals` collections; `calc.py` already defined `CRISIS_RATE_CENTS`, `CRISIS_DEADLINE_HOURS` and `referral_priority()`; `common.py` already carried `ERR_CRISIS_DEADLINE_PASSED`, `ERR_CRISIS_NOT_DUE`, `ERR_CRISIS_WINDOW_OVERLAP`; `store.py` already exposed `add_hours()`; and `r_applications.py` already wrote an auto-referral row into `db.weatherization_referrals` on TIER_1 approval. All of it was unreachable dead code.

These gaps were repaired in Step 7 (see below).

## Step 7: Run Tests and Iterate — 2026-07-10T03:52:00.000Z

**Execution deviation (deliberate, semantics preserved).** Two constraints were imposed on this resumed run. (1) The 8-round stability sweep was executed as **4 sequential waves of 2 concurrent rounds** instead of 8 fully-concurrent rounds, because 5 sibling PRD-bench tasks were running Step 7 on the same 8-core host; 5×8 concurrent per-test-server boots produce spurious "could not be restarted" boot-timeout ERRORs. The pass criterion is unchanged: all 8 rounds run to completion, the failing-test set is the **union across all 8 rounds**, and the sweep passes only when 8/8 rounds satisfy `passed == total`. (2) Each wave ran as a **foreground** blocking call, because the prior `claude -p` early-exited while yielding on a backgrounded sweep. Consequently Step 7 was driven by the orchestrator directly rather than by a long-lived subagent; this summary is therefore the orchestrator's own, not a pasted subagent summary.

**Iterations run: 1.** The baseline 8-round sweep passed on the first attempt *after* the Step 6 gaps documented above were repaired. No diagnostic fix cycle was ever entered, because no test ever failed for a behavioral reason — the pre-repair state failed at server boot, before pytest collected anything.

**Sweep result (baseline, post-repair):**

```
round 1: passed 40/40 failed=0 errors=0 skipped=0 OK
round 2: passed 40/40 failed=0 errors=0 skipped=0 OK
round 3: passed 40/40 failed=0 errors=0 skipped=0 OK
round 4: passed 40/40 failed=0 errors=0 skipped=0 OK
round 5: passed 40/40 failed=0 errors=0 skipped=0 OK
round 6: passed 40/40 failed=0 errors=0 skipped=0 OK
round 7: passed 40/40 failed=0 errors=0 skipped=0 OK
round 8: passed 40/40 failed=0 errors=0 skipped=0 OK

union of failing tests across 8 rounds: (empty)
VERDICT: PASS — 8/8 rounds passed==total
```

**Tests deleted: 0.** No test asserted a scaffold-only rule; no test reached the STEP 1 coverage / unique-derivability gate, because none failed.

**Fixes applied to `test_suite/`: 0.**

**Fixes applied to `test_helpers/`: 0.**

**Fixes applied to `implementation/`: 3 files added, 0 files modified, 0 files deleted.** These are Step 6 completion repairs, not test-driven weakenings. Every added behavior traces to a verbatim PRD sentence; no PRD-required check was removed or relaxed; no entity data is seeded at startup; storage remains in-memory only.

1. **`app.py` (new, 74 lines)** — the entrypoint `start.sh` already required. Builds the Flask app via `create_app()`, calls `register(app)` on all 11 route modules, and installs error handlers: `ApiError → error_response(error_id, message)`; `NotFound → ERR_NOT_FOUND`; `MethodNotAllowed → ERR_NOT_FOUND`; generic `HTTPException` with code 400 → `ERR_VALIDATION`. Serves on `0.0.0.0:$PORT` (default 10000), `threaded=True` (the suite exercises OCC/concurrency on `expected_pool_version`), `use_reloader=False` so `exec` stays in the foreground per INSTRUCTION.md.

2. **`r_crisis.py` (new, 5 endpoints)** — implements PRD §3.8 verbatim. Create: body FKs resolve first (`ERR_INVALID_REFERENCE`, 422), then `program_component == CRISIS` (`ERR_POOL_COMPONENT_MISMATCH`, 422), then the half-open `[reported_at, resolve_by)` window-overlap check against this household's `OPEN` crises, adjacency at a `resolve_by` boundary permitted (`ERR_CRISIS_WINDOW_OVERLAP`, 409); stamps `reported_at` from the logical clock, `resolve_by = reported_at + 48h`, `estimated_benefit_cents = CRISIS_RATE_CENTS[crisis_type]`, `status = OPEN`. Resolve: requires `OPEN` (`ERR_INVALID_STATE`), clock **strictly before** `resolve_by` (`ERR_CRISIS_DEADLINE_PASSED`), pool neither `DEPLETED` nor `CLOSED` (`ERR_POOL_DEPLETED`); computes `resolved_benefit_cents = min(estimated_benefit_cents, pool.available_cents, account.current_balance_cents + account.arrearage_cents)`; creates the expedited `CRISIS` pledge via the existing `pledge_ops.create_pledge` (`application_id=None`, `vendor_id` from the utility account, `PLEDGED`), reserving the pool. Breach: requires `OPEN` (`ERR_INVALID_STATE`) and clock **at or after** `resolve_by` (`ERR_CRISIS_NOT_DUE`); sets `BREACHED`, creates no pledge, leaves `resolved_benefit_cents` unset. Plus GET-one and GET-list (filters: household_id, utility_account_id, funding_pool_id, status).

3. **`r_referrals.py` (new, 4 endpoints)** — implements PRD §3.9 verbatim. Create: `household_id` must resolve (`ERR_INVALID_REFERENCE`); optional `application_id`, validated as a body FK under the §2.9 global rule; `referral_reason ∈ {HIGH_ENERGY_BURDEN, TIER_1_AUTO, VENDOR_REPORTED}`; `status = REFERRED`; `priority` from the existing `calc.referral_priority()` (HIGH when reason is TIER_1_AUTO or household `has_elderly_or_disabled`; else MEDIUM when `has_child_under_6`; else LOW). Schedule: requires `REFERRED` (`ERR_INVALID_STATE`) → `SCHEDULED`. Plus GET-one and GET-list (filters: household_id, application_id, status).

**Verification independent of the sweep.** `app.app.url_map` registers exactly **44 method+path pairs**, matching the 44 scaffold endpoints (0 missing, 0 extra). All 16 implementation modules pass `ast.parse`. A standalone boot + live round-trip confirmed each new branch against PRD §3.8/§3.9: NO_HEAT estimate 50000; `resolve_by = reported_at + 48h`; overlapping create → `ERR_CRISIS_WINDOW_OVERLAP`; premature breach → `ERR_CRISIS_NOT_DUE`; resolve clamped by account owed (`min(50000, 965000, 35000) = 35000`); crisis pledge written with `application_id = null` and pool `reserved_cents` raised to 35000; post-deadline resolve → `ERR_CRISIS_DEADLINE_PASSED`; breach → `BREACHED` with `resolved_benefit_cents = null`; referral priority HIGH for a vulnerable household; re-schedule → `ERR_INVALID_STATE`; unknown household → `ERR_INVALID_REFERENCE`; `Applicant` reading a crisis → `ERR_FORBIDDEN`; no `_`-prefixed internal fields leak through the serializer.

**Note for Step 8.** The 40-test suite never exercises `crisis-benefits` or `weatherization-referrals`. The two new modules were therefore written against PRD prose alone, with no test pressure — the classic condition under which an implementer resolves a PRD silence by fiat. The silences resolved here are the focus list for Step 8.

## Step 8: Finalize PRD — 2026-07-10T03:56:00.000Z

**Not skipped.** The skip condition requires 0 `implementation/` fixes. Step 7 added 3 implementation files, so Step 8 ran. The Step 7 worklog entry above was inlined verbatim as `<step_7_diff>`.

Subagent summary, verbatim:

---

All five edits applied cleanly, all inline (no line-count change). Here is the exit summary.

## Line counts
- PRD.md: 265 lines; PRD_FINALIZED.md: 265 lines. Delta: 0 lines (+0%). All edits are inline insertions/revisions within existing lines.

## Changes (one per edit)
- **§3.8 (crisis resolve)** — insert — pinned the expedited crisis pledge's `benefit_period_start`/`benefit_period_end`/`expected_pool_version = null` and its bypass of all ordinary pledge-creation guards + its exemption from the account coverage-window overlap scan — `pledge_ops.py:36-46` (create_pledge persists+touches only), `r_crisis.py:104-115`.
- **§3.8 (crisis create)** — insert — `resolved_benefit_cents` is present and null on `OPEN` creation — `r_crisis.py:59`.
- **§3.8 (crisis breach)** — revise — changed "leaves `resolved_benefit_cents` unset" to "null" (present-and-null) — `r_crisis.py:130` (breach never sets it; stays None).
- **§3.9 (referral create)** — insert — an optional `application_id`, when supplied, is validated as a body FK yielding `ERR_INVALID_REFERENCE` — `r_referrals.py:24-25`.
- **§4 table (referrals list)** — revise — added `status` to the filter set ("household, application, or status") — `r_referrals.py:49-53`.
- **§2.4** — insert — unknown route / undefined HTTP method both yield `ERR_NOT_FOUND` (404) — `app.py:51-57` (NotFound and MethodNotAllowed handlers).

## Per-edit pre-edit search log
1. **Crisis pledge fields/guards.** (b) Enumerated: `r_pledges.py` ordinary create (runs full guard sequence, sets real `benefit_period_*` + `expected_pool_version`), `r_crisis.py` resolve (crisis), `pledge_ops.create_pledge` (shared persist+touch, no guards), `pledge_ops.account_has_period_overlap` (skips pledges with `_bp_start_dt/_bp_end_dt is None`). (c) Scoped wording to "this expedited pledge" so ordinary pledges keep their non-null window/OCC; confirmed the null-window skip claim matches `account_has_period_overlap`'s None-guard so ordinary pledges scanning later won't collide with the crisis pledge.
2. **`resolved_benefit_cents` lifecycle.** (b) Enumerated: create (set `None`, r_crisis.py:59), resolve (set to computed `min`, r_crisis.py:117), breach (untouched → stays `None`, r_crisis.py:130), `public()` in store.py (only strips `_`-prefixed keys, so `resolved_benefit_cents` is always emitted). (c) None — OPEN=null / RESOLVED=value / BREACHED=null all consistent.
3. **Referral `application_id` validation.** (b) Enumerated: `r_referrals.create_referral` (validates when present, household FK first), `r_applications._auto_refer` (auto-referral always sets a real source `application_id`, never validated because it always exists). (c) Wording limited to "when an `application_id` is supplied" on the direct-create path, leaving the auto-referral path unaffected; validation order (household then application) matches impl.
4. **Referral list filters.** (b) Enumerated: only `r_referrals.list_referrals` (household_id, application_id, status). Crisis list already reads "household / account / pool / status" and matches `r_crisis.list_crisis_benefits`, so no edit there. (c) None.
5. **Route-level not-found / method-not-allowed.** (b) Enumerated: `app.py` `_handle_not_found` (NotFound→ERR_NOT_FOUND/404) and `_handle_method_not_allowed` (MethodNotAllowed→ERR_NOT_FOUND/404); confirmed all defined method+path combos are registered so 405 only arises for genuinely undefined methods; `_handle_http_exception` 400→ERR_VALIDATION already covered by existing §2.9 prose (no edit). (c) Phrased as "matches no defined route" / "method not defined for an otherwise-known path" both →ERR_NOT_FOUND, consistent with both handlers.

Items considered but NOT edited: the `400 HTTPException → ERR_VALIDATION` mapping (already determined by §2.9's malformed-body rule); crisis GET-one/GET-list roles and crisis list filter set (§4 table already matches impl verbatim). No test-fixture-only items required PRD changes.

---

**Orchestrator verification (independent of subagent claim):** `PRD_FINALIZED.md` = 265 lines (PRD.md = 265, 0-line delta, all edits inline). `diff -u` shows exactly 6 changed lines across §2.4, §3.8 (×3), §3.9, and the §4 endpoint table — every one traceable to a `<step_7_diff>` item. Re-parsed `SCAFFOLD.yaml` against `PRD_FINALIZED.md`: 44/44 endpoint paths present, 22/22 `error_id` values present. Leakage sentinels (`test_recipe`, `scaffold_difficulty_design`, `scaffold_corner_design`, `Design:`) all absent.

## Step 9: Complete PRD — 2026-07-10T04:02:00.000Z

**Always runs.** Started from `workspace/PRD_FINALIZED.md` (Step 8 produced it).

Subagent summary, verbatim:

---

All invariants verified. 44 endpoint rows preserved (43 `/liheap` paths + the clock control), all 22 error ids intact, no scaffold sentinel text introduced.

## Summary

**File deltas** (`PRD_FINALIZED.md` → `PRD_COMPLETED.md`):
- Lines: 265 → 265 (all edits in-paragraph / in-table-cell, no new lines)
- Chars: 42,973 → 43,875 (+902)

**Counts:** 6 ambiguity-pins, 1 mismatch-revision (7 edits total; the ambiguity work spans 9 Edit calls because two ambiguity classes touched multiple table cells).

**Changes:**
- §2.3 — insert — ambiguity — pinned list tie-break (equal `created_at` broken by ascending insertion sequence) and pinned that list endpoints are NOT ownership-scoped (role gate + explicit filters only; a listing role sees all matching records) — `store.py:103-105` (`sort_key`) + `helpers.py:77-87` (`list_collection`, no per-record scoping in any list handler).
- §2.4 — insert — ambiguity — pinned that `updated_at` is present from creation with an initial value equal to `created_at` — `store.py:84-93` (`stamp_new`).
- §3.2 — revise — ambiguity — `ERR_SEASON_CLOSED` is raised whenever no matching non-closed pool exists (whether none was ever created OR all matching pools are CLOSED), not only when "the matching pool's status is CLOSED" — `r_applications.py:85,162-168` (`_matching_open_pool`).
- §3.4 — insert — ambiguity — pinned tie-break for the "greatest `created_at`" verified income doc (latest creation sequence wins on a `created_at` tie) — `r_applications.py:123` (`max(verified, key=sort_key)`).
- §3.7 — revise — mismatch — payment return decreases `lifetime_credited_cents` by the amount actually applied (`applied_to_arrearage_cents + applied_to_current_cents`), NOT by `credit_amount_cents`; these differ when the credit had unallocated excess, and the impl's symmetric form is what preserves the §2.8 invariant — `r_payments.py:119-121` (vs. remit's `+= applied_arr + applied_cur` at `r_payments.py:91`).
- §4 table — revise — ambiguity — pinned actual list filter fields: applications (`household_id`, `season_year`, `program_component`, `status`), income-documents (`application_id`, `status`), payments (`pledge_id`, `status`), bill-credits (`payment_id`, `utility_account_id`, `status`) — respective `list_*` handlers in `r_applications.py:66-71`, `r_income.py:47-50`, `r_payments.py:41-44`, `r_billcredits.py:21-25`.

**Notable finding:** The §3.7 return-cascade mismatch is a genuine correctness divergence — PRD prose would break the §2.8 conservation invariant on any partially-allocated credit; the implementation is internally consistent and is the alignment target, so the prose was revised to match it.

Areas checked and already uniquely pinned (no change needed): response envelope/meta fields, pagination bounds/defaults, pool status ladder, OCC version guard, single-read ownership scoping (covered by §2.1's general ownership rule), crisis half-open vs pledge closed-interval overlap, crisis resolve `min(estimated, available, owed)`, benefit round-then-sum + clamp, `touch()` cascade targets on close/cancel/remit/return/resolve, and the crisis expedited-pledge guard-skip list.

---

**Orchestrator verification (independent of subagent claim):** `PRD_COMPLETED.md` = 265 lines. Re-parsed `SCAFFOLD.yaml` against it: 44/44 endpoint paths present, 22/22 `error_id` values present; leakage sentinels all absent. Spot-checked the three highest-risk claims directly against source:
- §3.7 mismatch is real — `r_payments.py:91` remit does `lifetime_credited_cents += (applied_arr + applied_cur)` and `r_payments.py:119-121` return does `-= (credit["applied_to_arrearage_cents"] + credit["applied_to_current_cents"])`. Neither uses `credit_amount_cents`. PRD_FINALIZED's "decreased by `credit_amount_cents`" was wrong; PRD_COMPLETED's wording matches the code.
- §3.2 is real — `_matching_open_pool()` returns True only when a matching non-CLOSED pool exists, so a season with no pool at all also raises `ERR_SEASON_CLOSED`.
- §2.3 is real — `helpers.list_collection()` filters only on explicit field equality and never on `user_id`; none of the 8 `list_*` handlers pass identity into scoping.

**Artifact integrity check:** no file under `workspace/implementation/`, `test_suite/`, or `test_helpers/` has an mtime newer than `results.8.json` (the final Step 7 sweep artifact). Steps 8 and 9 modified only `workspace/PRD_FINALIZED.md` and `workspace/PRD_COMPLETED.md`, as required. The 8/8 passing sweep therefore still describes the implementation exactly as it stands.

## Pipeline Complete — 2026-07-10T04:02:00.000Z

Steps 1–9 all complete. Final artifacts:
- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`
- `workspace/INSTRUCTION.md`, `workspace/PRD.md`
- `workspace/PRD_FINALIZED.md` (Step 8), `workspace/PRD_COMPLETED.md` (Step 9)
- `test_helpers/` (9 modules), `test_suite/` (conftest + 4 modules, 40 tests, 0 deleted)
- `workspace/implementation/` (16 Python modules + start.sh + requirements.txt, 44/44 endpoints)
- Final gate: 8/8 rounds × 40/40 tests, empty failure union, under `--isolation per-test-server`.
