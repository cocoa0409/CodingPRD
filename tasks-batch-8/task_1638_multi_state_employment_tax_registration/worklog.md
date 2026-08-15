# Worklog — task_1638_multi_state_employment_tax_registration

## Step 1: Create Task Directory — 2026-08-14T04:04:00.000Z

Task directory `tasks/task_1638_multi_state_employment_tax_registration/` and `workspace/` were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE (no index scan performed).

## Step 2: Generate Scaffold — 2026-08-14T05:13:11.140Z

Scaffold generation complete. All three artifacts are in place and pass the official lint with a clean verdict on the first final run.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1638_multi_state_employment_tax_registration/`):
- `SCAFFOLD.yaml` — 115,863 bytes (2,205 lines); §1.0–§1.7 only, no difficulty/corner keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 84,713 bytes (764 lines); single top-level `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 128,551 bytes (1,137 lines); single top-level `scaffold_corner_design`

**Surface counts (§1.1–§1.7):** 15 entities, 79 endpoints, 31 error codes, 31 ordered validation rules, 12 calculations, 11 state machines, 6 roles (incl. `entity_backed:Employee`), 5 OCC concurrency rules (registration-create on Employer.version, election-create and assignment-override on Employee.version, ui-rate-create on Registration.version, location-change PATCH on its own version — covering the directive's duplicate-registration and conflicting-location-update targets).

**Difficulty axes (§1.8):** 21 instances across all nine rules — dual-variant calcs in 2 domains (deposit schedule provisional-vs-lookback, UI rate standard-vs-buydown 390→270); combinatorial formulas in modes (a) bracket/surcharge/clamp, (b) per-line-then-sum rounding pinned to 50,136 vs 50,137, (c) circular VC buy-down with pinned evaluation order (net savings literal 200,000); cyclic machines on Registration (reject→resubmit) and NexusCase (WATCH↔THRESHOLD_MET); depth-3 transitive cascades from location-change effectuation and from the DUE→LATE sweep; validation priority pairs state×temporal and temporal×referential; boundary probes on day-count (19 vs 20), deadline timestamp (±1s), and the 5,000,000-cent frequency split; cross-entity guards on 3 entity pairs; two overlap rules with contrasting half-open vs closed-interval semantics; compensating invariants on attribution totals and outstanding-penalty cents.

**Corner breadth (§1.9):** 51 active instances + 9 `excluded_because` stubs, spanning entities, state machines (incl. terminal lockdown, sweep auto-transitions, guard holds), calculations (weekend roll-forward 2026-10-31→11-02, penalty tier boundaries with 2,500-min/7,625-final literals, selector specificity tie-break, new-employer rate fallback 27,074), validations (all 31 error codes triggerable), endpoints (pagination envelope, filtered FK lists, computed reads), RBAC (ownership, SoD same-user cross-role), all 5 OCC rules, scheduled actions, and consistency.

**Verification:** `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (79 endpoints, 15 entities, 21+51 instances, 754 calls scanned). All fixture arithmetic was pre-computed and verified with Python (nexus boundaries, UI bracket math, VC savings, rounding divergence pair, penalty tiers, calendar dates). No sibling task directories were inspected. Forbidden race vocabulary scan: clean.

## Step 3: Copy Shared Files — 2026-08-14T05:13:40.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1638_multi_state_employment_tax_registration/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-14T05:32:00.000Z

PRD generated at `workspace/PRD.md` — 387 lines, 9,192 words.

## Structure

- **§1 Introduction** — 2 paragraphs (business context + the two design commitments: audit-grade aggregation and the explicit logical clock)
- **§2 Global Specifications** — 9 subsections: 2.1 RBAC (all 6 roles with identity prose; `Employee` entity-backed, five opaque), 2.2 Response Structure (verbatim fixed block, byte-identical including `req_RANDOMALPHANUM123456` and `"data": { }`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Logical Clock & Scheduled Sweep (default 2026-08-01T00:00:00Z, monotonic, full sweep inventory), 2.5 Common Resource Properties (all 15 entities carry `id`/`created_at`/`updated_at`/`version`; nominated increments enumerated), 2.6 Money/Basis-Points/Rounding (integer cents, round-half-up, per-line-then-sum pinned, STATUTORY floor exception), 2.7 Employer Posture & Counters (full compliance_posture calc), 2.8 OCC (all 5 rules with exact `expected_*_version` fields and `ERR_STALE_VERSION`/412), 2.9 Validation Order (31 scaffold validations rendered as 14 ordered tiers incl. the `ERR_EMPLOYEE_NOT_ACTIVE` tie-break after from-state)
- **§3 Business Logic** — 9 subsections (catalog setup → employee intake/local resolution → nexus → registration/calendar → elections → location changes → UI rates/VC → obligations/penalties → notices/abatement); all state transitions, side-effect cascades, and all 12 calculation formulas expressed in precise prose with constants embedded (e.g., "at least 20 employee-days or 5,000,000 cents ($50,000)", full 8-row UI bracket table, SEMIWEEKLY window schedule, 2%/5%/10% late tiers with 2,500-cent floor)
- **§4 Endpoint Definitions** — 79 rows, 4 columns only (Method, Path, Description, Authorized Roles)
- **§5 Error Code Catalogue** — 31 rows, 2 columns only

## Hard Contract Reports

Field coverage check: entities[].fields 121/121 present; request_body/input extras 14/14 present; query_params covered. Status: PASS

Rule coverage check: validations[] with priority 31/31 expressed; concurrency_rules[] OCC rejections 5/5 expressed; state_machines[].transitions 66/66 fully expressed; calculations[] 12/12 fully expressed; validations[] conditions 31/31 matchable to error_id; endpoints[].side_effects / applies_to all expressed; entities[].fields[] structured content reconstructible; sibling-branch symmetry 0 asymmetric. Status: PASS

Path purity check (§3 only): 693 backtick tokens scanned, 0 path/method leaks. Status: PASS

## Coverage notes

- All 15 entities, 79 endpoints (§4 table verified 0 missing), 12 calculations, 11 state machines covered.
- Forbidden files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) and sibling task directories never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T06:05:00.000Z

All checks pass. The generation is complete.

## Summary

**Task**: task_1638_multi_state_employment_tax_registration — generated `test_helpers/` (9 files) and `test_suite/` (11 files, 103 tests).

### Test counts
- **Queue A (Difficulty, §1.8): 40 tests** — 20 of 21 instances covered with exactly 2 tests each.
- **Queue B (Corner, §1.9): 63 tests** — 50 of 51 non-stub instances covered with ≥1 test each. All 9 `excluded_because:` stubs left untranslated (cross-references to queue-A instances verified to resolve).

### Skipped instances (2), per the PRD-first two-condition filter
1. **`Difficulty/compensating_invariant/location_reversal_conserves_attribution_totals`** — the instance's asserted post-reversal literals (OR `employee_days_ytd == 20`, `wages_ytd_cents == 164384`) hold only at clock 2026-08-20, but its own recipe advances the clock to 2026-08-21 before the reversal. Under the PRD §3.3 attribution model (days counted through "the clock"), recompute at 2026-08-21 yields 21 days / 172,603 cents. Not uniquely derivable from the PRD — a faithful implementer would fail the test. Gap left as a gap.
2. **`Corner/entities/agreement_computed_status_input_ignored`** — asserts the server ignores an undeclared `status` field in the create payload. PRD pins status as computed from the clock but never states whether extra undeclared fields are ignored vs. rejected via the §2.9 catch-all; a strict PRD-only implementer could 400 the request. Fails unique derivability.

### One recipe-chain repair (not a skip)
`Corner/calculations/late_penalty_provisional_then_final_tier` filed with `filed_at=2026-11-18` while the clock was still 2026-11-03 — PRD §3.8 forbids a future `filed_at`. I added the missing clock advance to 2026-11-18 before the file call; all asserted literals (late_days 16, penalty 7,625, paid 76,250) match the instance verbatim.

### Files
- `test_helpers/`: `__init__.py` (barrel), `types.py` (15 TypedDicts + 19 enums), `api_client.py` (62 endpoint methods), `api_errors.py` (31 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque role constants + `make_employee_headers` entity-backed builder + per-role user-id builders for SoD tests), `fixtures.py` (composite chains: confirmed-nexus, active withholding/UI registrations, EFFECTIVE UI rate at 390bp, VC lifecycle, MONTHLY late-deposit cascade).
- `test_suite/`: `conftest.py` + `test_01_employer_and_catalog.py`, `test_02_employee_intake_and_local_resolution.py`, `test_03_nexus_monitoring.py`, `test_04_registrations_and_schedule.py`, `test_05_withholding_elections.py`, `test_06_location_changes.py`, `test_07_ui_rates.py`, `test_08_voluntary_contributions.py`, `test_09_filing_obligations.py`, `test_10_notices_and_abatement.py`.

### Self-check results
- Stage 1: `py_compile` OK; `import test_helpers` OK; pyflakes clean (barrel re-export warnings are intentional).
- Stage 2: `pytest --collect-only` → 103 tests collected, 0 errors.
- Tag audit: every test has exactly one trailing `Design:` line resolving to a real instance; coverage targets met for both queues.
- Citation audit: 148 PRD citations, every one verified verbatim against PRD.md via an 8-word sliding-window grep.
- No `skip`/`skipif`/`xfail` markers; no scaffold/Table references in generated code.

## Step 6: Generate Implementation — 2026-08-14T06:05:30.000Z

Implementation complete and verified. All three smoke suites (≈180 assertions covering every workflow family) pass, including a fresh-process boot via `bash start.sh`.

## File list — `workspace/implementation/`

- `start.sh` — executable launcher: guarded `pip install` (no-op once Flask present), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask app, blueprint registration, envelope-shaped 404/405/APIError handlers, `app.run(host="0.0.0.0", port=int($PORT or 10000))`
- `core.py` — in-memory store (16 dicts keyed by UUID, no seeding, no disk), logical clock, error catalog (31 error IDs with exact HTTP statuses), response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; `limit`/`offset`/`total_count`/`has_more` in meta for lists), auth middleware (`X-User-ID`/`X-User-Role`), Employee-ownership check, OCC helper, `round_half_up` (exact Fraction arithmetic), pagination (default 10, clamp [1,100]), datetime parse/format (date-only → `T00:00:00Z`, created/updated at 3-fractional-digit millis)
- `domain.py` — attribution model (half-open segments + current-location fallback, hire/termination bounded), jurisdiction resolution (precedence_rank → specificity → created_at, COLLAPSED/NONE_FOUND trace), nexus recompute + cyclic auto-transitions, employer posture/counters, filing calendar generation (MONTHLY/QUARTERLY/SEMIWEEKLY windows, weekend roll-forward, NEXT_DAY tier), per-line-rounded obligation amounts (withholding / UI wage-base slice / local resident-vs-nonresident), tiered late penalties with in-place notice update, VC buy-down projection, abatement eligibility, location-change effectuate/reverse cascades, and the scheduled sweep
- `routes_a.py` / `routes_b.py` / `routes_c.py` — all route handlers with PRD §2.9 validation ordering (headers → role → existence → ownership → date sanity → from-state → OCC → safety gates → SoD → uniqueness → referential → temporal → fiscal → general sanity)

## Counts

- **Endpoints: 79** (1 clock + 78 resource/action routes; every row of the scaffold endpoint table)
- **State machines: 11** (Employee, NexusCase, Registration, WithholdingElection, LocalAssignment, UIRate, VoluntaryContribution, LocationChange, FilingObligation, AgencyNotice, AbatementRequest) with all preconditions, SoD gates, and cascade side effects
- **Calculations: 12** (nexus threshold, deposit schedule PROVISIONAL/LOOKBACK, UI experience rate standard/buy-down, VC optimization, jurisdiction resolution, withholding/UI/local obligation amounts, filing calendar, late penalty provisional/final, abatement eligibility, compliance posture)

## Logical clock / scheduled sweep

Module-level `db.clock` (default `2026-08-01T00:00:00Z`); `POST /etax/_clock/set_current_utc` (TaxDirector only) rejects backward moves with `ERR_INVALID_REQUEST`, then synchronously runs `run_sweep()`: agreement status recompute (closed-interval ACTIVE/EXPIRED), election VALIDATED→ACTIVE / →EXPIRED, PROPOSED VC→EXPIRED past deadline, obligation SCHEDULED→DUE→LATE with penalty-notice cascade and daily `late_days`, APPROVED location-change effectuation cascade (employee move + segment truncation/creation + dual-state nexus recompute + posture), and final employer posture recompute. Every sweep mutation refreshes `updated_at` and bumps `version`.

## start.sh confirmation

Verified with `PORT=19873 bash start.sh`: binds `0.0.0.0`, foreground via `exec`, HTTP-ready in ~2s, dependency install guarded by `python3 -c "import flask"` so per-test reboots skip pip. Fresh boots start with provably empty stores (all 13 list endpoints return `total_count: 0`).

Notable judgment calls (PRD-compliant interpretations): truncated assignment segments keep `CURRENT` status with a bounded `effective_to` unless zero-length (literal scaffold reading); sweep expiry checks use strict `effective_to < now`; agreement `effective_from == effective_to` (single-day closed interval) allowed; `rhu` implements true half-up toward +∞ (differs from away-from-zero only on negative .5 reserve ratios).

## Step 7: Run Tests and Iterate — 2026-08-14T06:22:00.000Z

All 8 rounds pass 103/103. The fix holds under the full parallel stability sweep.

---

## Summary

- **Iterations run:** 2 (sweep 1: 96/103 in all 8 rounds with 7 deterministic failures; sweep 2 after fixes: 103/103 in all 8 rounds, zero failures, zero flakes).

- **Tests deleted:** none. Every failing assertion traced to a verbatim PRD rule; both failure clusters were test-artifact bugs, not implementation bugs, and no PRD-silence or unique-derivability collapses were found.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1638_multi_state_employment_tax_registration/test_helpers/fixtures.py` — `setup_monthly_or_with_late_deposit`: the fixture asserted exactly one LATE deposit at clock 2026-09-16, but PRD §3.8 ("A zero-amount obligation goes late without penalty and without a notice") means the zero-amount July deposit (employee hired 2026-08-01, zero attributed July days) is also LATE — only the 38,750-cent August deposit produces a notice. The fixture now asserts exactly two LATE deposits and selects the nonzero August one as `late_obligation`. Unblocked 5 tests across test_09/test_10.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1638_multi_state_employment_tax_registration/test_suite/test_04_registrations_and_schedule.py` — `TestSubmitRequiresConfirmedNexus._setup_threshold_met_not_confirmed`: passed the Employer `version` captured at creation (1) as `expected_employer_version`, but the intervening WATCH→THRESHOLD_MET nexus transition recomputes Employer posture GOOD_STANDING→WATCH, a mutation that bumps `version` per PRD §2.7 + §2.5. Added a `get_employer` re-fetch after the recompute (the same pattern sibling setups already use). Unblocked both test_04 tests.

- **Fixes applied to `implementation/`:** none. The implementation's behavior was PRD-correct in both clusters (Employer version bump on nexus-driven posture change; zero-amount obligation transitioning to LATE without a notice).

## Step 8: Finalize PRD — 2026-08-14T06:32:00.000Z

Done. PRD_FINALIZED.md written with exactly one in-place revision; everything else verified already-determined.

## Summary

**Line counts / %-delta:** PRD.md = 387 lines, PRD_FINALIZED.md = 387 lines. 0% line-count delta; the diff is a single-line in-place revision at line 116 (§2.7).

**Changes (one bullet per change):**
- §2.7 — revise — the final sentence "Each such recomputation is a mutation of the Employer under §2.5" was unconditional and would license bumping Employer `version`/`updated_at` on every recompute trigger (including no-op clock sweeps and no-change nexus recomputes); revised to "Each such recomputation that changes at least one of these aggregates is a mutation of the Employer under §2.5; a recomputation that leaves every aggregate unchanged is not a modification and refreshes neither `updated_at` nor `version`." — impl: `workspace/implementation/domain.py:79-82` (the `changed` guard gating `touch(emp)`), with `touch` defined at `workspace/implementation/core.py:181-183`.

**No-edit verification for the other Step 7 site (zero-amount LATE, traces to the `test_helpers/fixtures.py` fix):** PRD §3.8 already pins the impl behavior twice — the DUE→LATE transition sentence carries no amount condition ("Once the current date reaches the day after `due_date` while the obligation is still `DUE`, it becomes `LATE`"), and the cascade paragraph states verbatim "A zero-amount obligation goes late without penalty and without a notice." Impl `workspace/implementation/domain.py:820-826` does exactly that (unconditional DUE→LATE; `create_late_penalty_notice` only when `amount_due_cents > 0`; `recompute_employer` either way). Uniquely determined — prose kept verbatim.

**Per-edit pre-edit search log:**
- Edit 1 (§2.7 recompute-mutation semantics):
  - (a) Subject: whether an Employer aggregate/posture recomputation refreshes `updated_at` and increments `version`, including when the recomputation produces no value change.
  - (b) Impl paths enumerated and read/grepped: `recompute_employer` (domain.py:47-82, sole recomputation function; `touch` only under the `changed` guard); `touch` (core.py:181-183); every `recompute_employer` callsite via grep — domain.py:186 (`recompute_nexus_case`), 736/761/773 (location-change effectuate/reverse, employee terminate), 826+841 (`run_sweep`, incl. the zero-amount LATE branch), routes_a.py:461/476 (nexus confirm/exempt), routes_b.py:99 (registration create), 183 (activate), 219 (close), routes_c.py:577 (obligation file/final penalty), 666 (notice intake), 711 (escalate), 737 (resolve), 749 (notice close), 922 (abatement decision); the only unconditional Employer `touch` — registration creation at routes_b.py:98, which is not a recomputation and is separately pinned by §2.5/§3.4 (+1 on creation, asserted by test_04:415); other `touch(emp)` hits (domain.py:723/746/767, routes_b.py:398/598) verified by reading context to be Employee records, not the Employer.
  - (c) Wording adjustment: scoped the sentence to "recomputation[s] of these aggregates" so registration creation's unconditional increment and all Employee `touch` paths are untouched; kept the "Each such …" anchor so the trigger list and §2.5's general modification rule jointly cover the clock-sweep recompute (§2.4) as well; explicitly named both `updated_at` and `version` since `touch` drives both and the guard suppresses both.

Output file: `workspace/PRD_FINALIZED.md`

## Step 9: Complete PRD — 2026-08-14T06:52:00.000Z

All 30 changes are in place. The file is written and verified.

## Summary

**Source vs output:** `workspace/PRD_FINALIZED.md` (387 lines, 69,956 chars) → `workspace/PRD_COMPLETED.md` (389 lines, 75,547 chars). Char-delta **+5,591**, line-delta **+2** (the only new paragraph, in §2.2; every other change is an in-paragraph insert/revision; no sections added or removed).

**Counts:** 27 ambiguity-pins, 3 mismatch-revisions (30 total).

**Changes (section — insert|revise — class — what — impl ref):**

- §2.2 — insert — ambiguity — unknown paths and unsupported methods are rejected `ERR_NOT_FOUND`/404 in the error envelope — app.py:26-35
- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` are clamped to bounds; non-integer values rejected `ERR_INVALID_REQUEST` — core.py:378-400
- §2.3 — insert — ambiguity — `created_at` ties broken by creation sequence — core.py:401
- §2.3 — insert — ambiguity — each list endpoint supports a fixed filter set (others ignored); filters match exact case-sensitive equality; boolean filters accept only literal `true`/`false`, integer filters require integer text, else 400 — core.py:407-452
- §2.6 — revise — ambiguity — round half up rounds an exact .5 toward +∞ (−0.5 → 0, −1.5 → −1), observable only in negative reserve ratios (orchestrator note 4, verified: `rhu(-1,2)=0`) — core.py:157-163
- §2.9 item 3 — insert — ambiguity — a wholly omitted body FK is reported `ERR_NOT_FOUND` on election creation (NexusAnalyst), assignment override (`employee_id`), and UI-rate intake (`registration_id`); other omitted fields fall to rule 14 — routes_b.py:329-330, 573-574; routes_c.py:62-63
- §2.9 item 5 — revise — **mismatch** — blanket "strictly earlier" split: half-open pairs (elections) require strict, closed pairs (agreements) allow equality (orchestrator note 3) — routes_a.py:191-192, routes_b.py:324-325
- §3.1 — insert — ambiguity — agency kind-specific rate fields optional; absent rate reads as 0, absent `ui_wage_base_cents` imposes no cap — routes_a.py:137-143; domain.py:386, 422, 427-429, 665-667
- §3.1 — insert — ambiguity — agreement status boundaries are exact instants: `SCHEDULED` strictly before `effective_from`, `ACTIVE` at exactly `effective_from` through exactly `effective_to`, `EXPIRED` only when clock strictly later than `effective_to` (orchestrator note 2) — domain.py:779-784
- §3.2 — revise — **mismatch** — inactive-location rejection scoped to resolve/override/location-change intake; employee intake creates the initial segment without consulting `is_active` — routes_a.py:302-344 (no check); routes_b.py:544-545, 582-583; routes_c.py:369-370
- §3.2 — insert — ambiguity — duplicate `employee_ref` rejected `ERR_INVALID_REQUEST` — routes_a.py:313-315
- §3.2 — revise — ambiguity — truncation targets the open `CURRENT` segment; positive-length truncation keeps it `CURRENT` with bounded `effective_to` (multiple `CURRENT` segments may coexist, at most one open); only zero-length remainders are `SUPERSEDED` (orchestrator note 1) — domain.py:277-295
- §3.3 — insert — ambiguity — trailing-90d window is [clock−90d, clock date] inclusive — domain.py:145, 152
- §3.3 — insert — ambiguity — when several segments cover a day, the most recently created wins — domain.py:88-100
- §3.3 — insert — ambiguity — every recompute refreshes `last_recomputed_at`/`updated_at` and increments the case `version` even when nothing changes — domain.py:168, 185
- §3.4 — insert — ambiguity — registration creation without an existing Employer is `ERR_NOT_FOUND` — routes_b.py:56-60
- §3.4 — revise — ambiguity — closure's "linked notice" = `registration_id` match or `filing_obligation_id` naming one of the registration's obligations — routes_b.py:204-215
- §3.4 — revise — ambiguity — schedule recomputation is not state-gated and increments the registration `version` on every invocation, frequency change or not — routes_b.py:223-280
- §3.5 — insert — ambiguity — Employee-role election creation checks ownership before body sanity; omitted `employee_id` → `ERR_NOT_RESOURCE_OWNER` — routes_b.py:308-310
- §3.5 — revise — ambiguity — `supersede_existing` supersedes *all* prior same-type `VALIDATED`/`ACTIVE` elections, linking the most recently created — routes_b.py:382-396
- §3.5 — revise — ambiguity — sweep election expiry is strict (`effective_to` < clock) and is evaluated before activation, so an expired `VALIDATED` election goes straight to `EXPIRED` (orchestrator note 2) — domain.py:799-809
- §3.6 — insert — ambiguity — location-change create evaluates ownership before general sanity; omitted `employee_id` → `ERR_NOT_RESOURCE_OWNER`, not a missing-field error (orchestrator corner) — routes_c.py:353-354, 358-359
- §3.6 — insert — ambiguity — `impact_summary` names a single state when old and new states coincide — routes_c.py:464-469
- §3.6 — revise — **mismatch** — reversal leaves the effectuation segment `SUPERSEDED` but open-ended, so days ≥ `effective_date` still attribute to it under the most-recent-segment rule; only days before `effective_date` return to the reinstated segment (verified by simulation against domain.py) — domain.py:739-761, 88-100
- §3.7 — revise — ambiguity — UI-rate intake against a non-`ACTIVE` registration is `ERR_INVALID_STATE_TRANSITION` — routes_c.py:56-58
- §3.8 — insert — ambiguity — a `UI_RETURN` row always carries `amount_due_cents` of zero — domain.py:521
- §3.8 — revise — ambiguity — `SCHEDULED`→`DUE` fires as soon as the clock is strictly past the midnight carrying `period_end` (i.e., any time on the period's last day); `DUE`→`LATE` fires exactly at midnight of the day after `due_date` — domain.py:817-821
- §3.8 — insert — ambiguity — filing from `LATE` refreshes the shared notice's `severity` alongside `penalty_amount_cents` — routes_c.py:570-576
- §3.9 — insert — ambiguity — drafting against a non-`PENALTY_ASSESSMENT` notice → `ERR_INVALID_REQUEST`; against a `RESOLVED`/`CLOSED` notice → `ERR_INVALID_STATE_TRANSITION` — routes_c.py:769-774
- §3.9 — insert — ambiguity — withdrawal is gated by role only; the withdrawer need not be the preparer — routes_c.py:926-934

**Verification notes:** latest runner results show 103/103 tests passing (results.1-8.json all green); all four orchestrator judgment calls were confirmed in code (two empirically via a runtime simulation of the impl modules) and pinned; the one substantive mismatch found beyond the flagged notes — post-reversal attribution residue — was confirmed by direct simulation and revised into the PRD rather than smoothed over.
