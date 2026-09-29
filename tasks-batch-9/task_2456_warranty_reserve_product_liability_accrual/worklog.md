# Worklog — task_2456_warranty_reserve_product_liability_accrual

## Step 1: Create task directory — 2026-09-02T20:04:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2456_warranty_reserve_product_liability_accrual` and its `workspace/` subdirectory. Index pre-assigned by the invoking pipeline (2456); no scan of `./tasks/` performed, per instruction (32 concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate Scaffold — 2026-09-02T22:18:00.000Z

Orchestrator note: the first Step 2 subagent was killed by an upstream API timeout after ~63 min with zero files on disk. Retried with a fresh subagent plus an explicit instruction to persist each artifact to disk incrementally rather than in one final write. The retry succeeded. Verified post-hoc: all three YAMLs exist, parse under `yaml.safe_load`, and carry the correct top-level keys (SCAFFOLD.yaml 2134 lines / no design keys; DIFFICULTY 1363 lines / single `scaffold_difficulty_design`; CORNER 3906 lines / single `scaffold_corner_design`).

Subagent summary (verbatim):

All three artifacts are complete and lint-clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2456_warranty_reserve_product_liability_accrual/`):
- `SCAFFOLD.yaml` — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**SCAFFOLD.yaml counts:** 14 entities, 6 state machines, 3 OCC concurrency rules (§1.2.1), 13 calculations, 36 validation rules (priority-ordered ladder), 59 endpoints, 48 errors, 6 roles. Profile: `expert_plus`, archetypes ledger_reconciliation / compliance_audit, `api_prefix: /warranty`, flat topology, cyclic state-machine shape, segregation_of_duties role model, immediate consistency; layers dual_variant_calculation, cascading_side_effects, optimistic_concurrency, derived_field_reconciliation.

**§1.8 difficulty design:** 9 categories × 2 = 18 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).

**§1.9 corner design:** 9 sections, 99 instances total — entities 13, state_machines 16, calculations 16, validations 24, endpoints 6, errors 7, rbac 9, cross_cutting_complexity_layers 6, consistency_model 2. Of those, 79 carry full `test_recipe`s and 20 are `excluded_because` stubs citing named §1.8 instances (no duplicate names; every stub validated against an existing §1.8 instance name). All 48 error codes are triggerable by at least one §1.8/§1.9 instance.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2456_warranty_reserve_product_liability_accrual/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2456_warranty_reserve_product_liability_accrual/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2456_warranty_reserve_product_liability_accrual/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     79
  Calls scanned (§1.8+§1.9):  784

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

One fix was needed to reach clean: check (f) flagged `RemedyOption.field_action_id -> FieldAction` because the sub-resource GET was declared as `/warranty/field-actions/{fieldActionId}/remedy-options`; the lint (and SKILL §1.5) require the literal `{id}` placeholder in the parent segment, so that GET path is now `/warranty/field-actions/{id}/remedy-options` (the POST sibling keeps `{fieldActionId}`; only GET paths participate in check (f)). No other scaffold changes. The hard constraint was honored — no sibling `task_*/` directory was listed, read, or grepped.

## Step 3: Copy Shared Files — 2026-09-02T22:19:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T22:33:00.000Z

Orchestrator truncation check (the known doc-generator failure mode): PASS. `workspace/PRD.md` is 457 lines; section headings run §1 → §2.1–2.11 → §3.1–3.9 → §4 → §5 with no gaps; the file ends on the final row of the §5 error table (`| \`ERR_RESERVE_CAP_EXCEEDED\` | 422 |`), a real section boundary with a complete final row rather than a mid-sentence cut. Independent counts confirm coverage: 59 endpoint table rows (matches SCAFFOLD's 59 endpoints) and 48 distinct `ERR_*` tokens (matches SCAFFOLD's 48 errors). No regeneration needed.

Subagent summary (verbatim):

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2456_warranty_reserve_product_liability_accrual/workspace/PRD.md` — **457 lines**, written across 8 incremental Write/Edit calls. Document ends cleanly at the final row of the §5 error table (no truncation, no audit footer).

## Section list

- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 11 subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim, byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and Revision Counters · 2.5 The Logical Clock · 2.6 Integer Money, Basis Points and the Rounding Convention · 2.7 Optimistic Concurrency on Period and Field-Action Versions · 2.8 Segregation of Duties in the Reserve Close · 2.9 Validation Precedence (all 36 rungs in order) · 2.10 The Family Reserve Ledger and Governance Posture · 2.11 Cascade Discipline
- §3 Business Logic — 9 subsections: 3.1 Fiscal Accrual Period Calendar · 3.2 Product Families, Vintages, Failure Modes and Claim History · 3.3 Estimating and Posting the Base Warranty Accrual · 3.4 Reserve Adequacy and the Trend True-Up · 3.5 Campaigns, Recalls and Field Actions · 3.6 Extended Service Contracts and Revenue Deferral · 3.7 Supplier Recovery, Negotiation and Collectability · 3.8 Product-Liability Reserves and IBNR · 3.9 Rollforward Disclosure and Significant Campaign Exposures
- §4 Endpoint Definitions (4-column table, 59 rows)
- §5 Error Code Catalogue (2-column table, 48 rows)

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 134 required, 134 present, 0 missing
- endpoints[].request_body: 70 required, 70 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
- endpoints[].path_params: 14 required, 14 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 36 checked, 36 expressed in prose (ordered ladder in §2.9 with applies_to sets enumerated), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_period_version / expected_field_action_version + error_id + 412 all named in §2.7), 0 missing
- state_machines[].transitions: 28 checked across 6 machines (AccrualPeriod 4, WarrantyAccrual 5, FieldAction 7, SupplierRecovery 7, LiabilityReserve 3, ServiceContract 2), 28 fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed with constants embedded in business context (25000 bps lifetime development = 2.5x, 6000/4000 bps blend, 9500 cents/hour labour, 1200 bps/month lag capped at 6000, 15000 bps IBNR cap, 25 cents/unit floor, 8000/12000/15000 bps trend tiers, 1000/3000/6000/10000 bps claims curve, 9000/6000/2500/0 bps collectability, 7500/4000 bps realization, 8000/10000 bps posture, 12 months / 5000 units maturity, 50,000,000 cents significant exposure, 30-day quiet buffer), 0 missing
- validations[] conditions: 36 checked, 36 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 59 endpoints checked, all side effects expressed, 0 missing
- entities[].fields[] structured content: 134 checked (types, defaults, initial values, enum member sets, common_fields:false on ClaimObservation and ReserveRollforward), 134 reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (APPROVED/REJECTED decision, SETTLED/WRITTEN_OFF close, HISTORICAL_RATE/ANALOG_BLEND, STRAIGHT_LINE/CLAIMS_PATTERN, EXPECTED_VALUE/CONTRACTUAL_FLOOR, DRAFT→ASSERTED vs NEGOTIATION→ASSERTED, REVIEWED/RETURNED), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 817
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Notes for the worklog

- All 6 roles named with `identity:` translated (`SupplierRep` is entity-backed on `Supplier`; the other five are opaque operator ids, with every attribution field they land in named).
- Two scaffold spots where the state machine is stricter than validation priority 11 (accrual create/propose/revise require the period in `OPEN` or `ANALYSIS_LOCKED`, not merely non-`CLOSED`) were written to the stricter state-machine reading with `ERR_PERIOD_CLOSED` as the code, matching both sources.
- Pinned rounding/clamp orders are called out explicitly as observable (per-failure-mode round-then-sum; single rounding of the blended weighted sum; per-unit take-rate rounding before multiplying by unit count; per-accrual earned rounding reused in step 5; IBNR cap inner / exposure floor outer so the floor wins).
- No `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-09-03T01:36:00.000Z

Orchestrator note on concurrency: Steps 5 and 6 ran concurrently as required. Because the harness returns each Agent launch as its own tool result, they were launched as two consecutive background agents rather than two tool uses in one message; their execution windows overlapped for essentially the whole of Step 6 (Step 6 finished at ~23:12 while Step 5 ran until ~01:36), so the throughput benefit was preserved. The physical-isolation benefit was preserved by explicit instruction instead of by directory absence: Step 6's prompt hard-forbade reading, listing, globbing or grepping `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml`, and its returned summary confirms compliance.

Subagent summary (verbatim):

Both remaining files are written and verified. The generation job is complete.

## Files written

**Stage 1 — `test_helpers/`** (9 modules): `types.py`, `api_client.py` (`WarrantyApiClient`, one method per endpoint + `*_raw` creators), `api_errors.py` (full error-id catalogue), `constants.py`, `test_users.py` (5 roles + supplier-rep headers, SoD-friendly `_ALT_` ids, malformed-header builders), `factories.py` (payload builders per entity), `assertions.py`, `fixtures.py` (world-building helpers), `__init__.py` (flat re-export surface).

**Stage 2 — `test_suite/`**: 27 files, **132 tests**.

| Queue | Files | Tests |
|---|---|---|
| A (Difficulty §1.8) | `test_01`–`test_18` | **53** |
| B (Corner §1.9) | `test_20` entities 11, `test_21` state_machines 11, `test_22` calculations 13, `test_23` validations 19, `test_24` endpoints 6, `test_25` errors 3, `test_26` rbac 9, `test_27` cross_cutting 5, `test_28` consistency 2 | **79** |

Files added this session: `test_27_corner_cross_cutting.py` (three OCC version guards, derived `significant_exposure_count`/disclosure reconciliation incl. rollforward snapshot, cascade-hop-four-skipped-at-NORMAL) and `test_28_corner_consistency.py` (post visible in its own response + family ledger + `open-actuarial-review` guard; clock move repricing contract recognition and cohort `exposure_status`).

## Verification performed
- Every module imports cleanly under `PYTHONPATH=.`; every `api.<method>` referenced exists on `WarrantyApiClient` (0 unknown).
- Tag audit: 132 tests / 132 `Design:` lines, one per test, zero untagged, zero dual-tagged, zero dangling — all resolve to real `name:` entries in the two design yamls.
- Coverage: **18/18** Difficulty instances and **79/79** non-stub Corner instances translated. The 20 Corner instances carrying `excluded_because:` were intentionally not translated (stubs, redundant with queue-A depth tests or with other corner instances).
- Citation audit (`/tmp/audit3.py`): all quoted PRD snippets verbatim and attributed to the correct `§N.M`. Two residual rows are script artifacts, not defects: `test_04` (PRD sentence contains a nested quote) and `test_26` (fragment split on a mid-sentence comma).

## Instances skipped
None for lack of PRD coverage — every non-stub instance passed the two-condition filter.

## Three places where the PRD overrode the design (asserted the PRD)
1. `corner_supplier_rep_can_respond_to_its_own_asserted_recovery` — design expects status `SUPPLIER_RESPONDED`; PRD §3.7 moves `ASSERTED` → `NEGOTIATION`. Asserted `NEGOTIATION`.
2. Same instance — design expects `recognized_recovery_cents == 240000`; PRD §3.7's HIGH collectability weight (9000 bps, under a 100,000,000 ceiling) yields **1,080,000**. Asserted 1,080,000.
3. `corner_immediate_consistency_posted_accrual_is_visible_in_the_same_request` — design expects `reserve_posture == ELEVATED` at 7275 bps; PRD §2.10 requires ≥8000 bps for `ELEVATED`. Asserted **NORMAL**.

## Step 6: Generate Implementation — 2026-09-02T23:12:00.000Z

Subagent summary (verbatim):

Done. The implementation is complete, boots clean from a fresh process, and the leftover smoke-test server has been killed (ports 10711/10787 free, `__pycache__` removed).

## Modules (all under `/home/ubuntu/github/CodingPRD/tasks/task_2456_warranty_reserve_product_liability_accrual/workspace/implementation/`)

Foundation: `app.py`, `start.sh`, `requirements.txt` (`Flask==3.0.3`), `errors.py` (all 48 error IDs + HTTP statuses + `ApiError`/`fail`), `response.py` (meta envelope, `req_<20 alnum>` ids, 3-fraction-digit Z timestamps, pagination meta), `numeric.py` (`round_half_up` on exact rationals, ties away from zero), `store.py` (14 in-memory collections, logical clock, monotonic `created_at` + `_seq` ordering, global `RLock`), `serialize.py` (per-kind dumps; period disclosure counters derived at read time), `auth.py` (rungs 1-2, 6 roles), `validation.py` (typed `Field` shape checker, rung 5, pagination), `lookups.py` (collection→404 error map).

Business logic: `services/calc.py` (all 13 calculations, including the three dual-variant ones, plus the family reserve ledger/posture, supplier aggregates/rating, rollforward figures, and the clock-move recomputation sweep).

Routes: `routes/periods.py`, `catalog.py`, `accruals.py`, `field_actions.py`, `contracts.py`, `suppliers.py`, `liability.py`, `clock.py`.

## Coverage

- **Endpoints: 59/59** verified by enumerating `app.url_map` (excluding `/static`).
- **Entities: 14/14**; **state machines: 6/6** including the cyclic period reopen, the two independent FieldAction dimensions, and the terminal contract states with clock-driven auto-expiry in `created_at` ASC.
- **Calculations: 13/13**, hand-verified against worked examples (HISTORICAL_RATE and ANALOG_BLEND accrual, remedy per-unit and specific accrual, adequacy ratio/tier/true-up, STRAIGHT_LINE and CLAIMS_PATTERN recognition, IBNR with the pinned `max(floor, min(raw, cap))` clamp order, supplier cap with both EXPECTED_VALUE and CONTRACTUAL_FLOOR, rollforward).
- **Validations: all 36 rungs**, with the ladder (PRD §2.9) taking strict precedence over scaffold precondition ordering. Notable reconciliations, all now confirmed against the authoritative §2.9 text: rung 3 (SupplierRep scoping) before rung 4, with an unknown recovery id falling through to 404; rung 7 scoped to PATCH only; rungs 9/10 (optimistic concurrency, 412) before rung 11; rung 11 is a "not CLOSED" guard that fires even on accrual `post` (so a CLOSED period answers `ERR_PERIOD_CLOSED` there, while OPEN/ACTUARIAL_REVIEW fall to rung 12's `ERR_INVALID_STATE_TRANSITION`), whereas accrual create/propose/revise answer `ERR_PERIOD_CLOSED` for ACTUARIAL_REVIEW too per §3.3; rung 17 before rung 20 on `select-remedy`; field-action `decision` runs 12 → 18 → 19 → 30; recovery `close` runs 12 → 30 → 35; the `YYYY-QN` regex applies only to `observation_period_code`.
- Cascades are single-pass, never iterated to a fixed point (4-hop field-action approval, 5-hop recovery close), rows processed in `created_at` ASC, and derived-value writes bump `version` only when a stored value actually changes.
- Storage is in-memory dicts only; `store.reset()` at app construction leaves every collection empty and nothing is ever seeded, preloaded, or hardcoded.

## start.sh mechanics

`set -euo pipefail`, `cd "$(dirname "$0")"`, then a **guarded** dependency install (`python3 -c "import flask"` probe; pip runs only if the import fails), then `exec python3 app.py`. The guard matters because `--isolation per-test-server` re-runs `start.sh` before every single test across 8 concurrent rounds — an unconditional `pip install` there causes boot contention and flaky "could not be restarted" timeouts. `app.py` binds `0.0.0.0` on `PORT` (default 10000) with `threaded=True, use_reloader=False`.

I did not read, list, or grep `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, or `SCAFFOLD_CORNER_DESIGN.yaml`, and wrote nothing outside `workspace/implementation/`.

## Step 7: Run Tests and Iterate — 2026-09-03T03:35:00.000Z

Orchestrator verification (per the standing caution that a Step 7 subagent can report a clean sweep with no artifacts on disk): checked independently. All 8 files `workspace/implementation/results.{1..8}.json` exist and each reports `132 / 132` passed. Sweeps were run under `setsid nohup` as instructed, so no reaping-induced RemoteDisconnected pattern occurred; the subagent explicitly reports no load-induced flakiness across either sweep.

Step 8 gating decision: NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; there were 2 `test_suite/` fixes, so Step 8 runs. Note for Step 8's benefit: both fixes were fixture/setup bugs where the PRD's own §2.9 ladder and §3.5 window geometry vindicated the implementation, so it is a legitimate outcome for Step 8 to conclude that little or no PRD patching is warranted — the burden is on it not to invent edits.

Subagent summary (verbatim):

Clean 8-round parallel sweep achieved.

## Summary

**Iterations run:** 2 (one diagnostic sweep, one confirming sweep). Final sweep: all 8 `results.{1..8}.json` on disk, each `132 / 132` passed, 0 failed / 0 errors / 0 skipped.

**Tests deleted:** none. Both failures were STEP 2 test bugs (setup inconsistent with PRD), not PRD-silence cases.

**Fixes applied to `test_helpers/`:** none — both defects lived in test-local setup inside `test_suite/`.

**Fixes applied to `test_suite/`:**

- `/home/ubuntu/github/CodingPRD/tasks/task_2456_warranty_reserve_product_liability_accrual/test_suite/test_23_corner_validations.py` — `test_a_cohort_whose_warranty_has_already_run_out_cannot_be_accrued`. The test asserted `ERR_VINTAGE_EXPOSURE_EXPIRED` but its family classified `LIMITED` (600 units, no claim history) while the request used `method="HISTORICAL_RATE"`, so the PRD-faithful implementation correctly answered `ERR_INSUFFICIENT_CLAIM_HISTORY`. PRD §2.9 places the maturity gate at **rung 24** and the exposure gate at **rung 25**, so rung 24 legitimately pre-empts; the test's docstring claim that rung 25 sits "above rung 24's maturity gate" was factually wrong against the ladder. Fixed the setup so rung 25 is the *first* rung violated: `units_shipped` 600 → 6000 and added a claim observation with `months_in_service_to=24`, making the family `MATURE` per §3.2's "`MATURE` when `observed_history_months` is at least 12 **and** `observed_exposure_units` is at least 5000". Corrected the docstring and updated the trailing `observed_exposure_units` assertion to 6000 (§3.2 still counts `EXPIRED` vintages in that metric, which is what the assertion guards).

- `/home/ubuntu/github/CodingPRD/tasks/task_2456_warranty_reserve_product_liability_accrual/test_suite/test_27_corner_cross_cutting.py` — local `_campaign()` helper + `test_only_a_campaign_over_the_disclosure_threshold_moves_the_counter`. The helper hardcoded the same build window `2025-01-01..2025-06-30` for every campaign, so creating two campaigns on one family tripped PRD §3.5's 30-day buffered closed-interval check and the setup died on `ERR_FIELD_ACTION_WINDOW_CONFLICT` — the implementation was right. Parameterised the build window (defaults unchanged, so the other call site at `test_an_approval_that_leaves_the_posture_normal_spares_the_proposed_accrual` is untouched) and gave the two campaigns windows 123 days apart, clearing §3.5's "only a gap of 31 days or more is accepted".

**Fixes applied to `implementation/`:** none. The implementation was correct on both counts — in each case the PRD's own precedence ladder (§2.9) or window geometry (§3.5) vindicated it, so per the cardinal rules no PRD-required check was weakened.

**Notes:** the first sweep's raw `sweep.log` appeared to show 4 distinct `FAILED` names, but that was line interleaving across the 8 concurrent pytest processes — the JSON results showed the same deterministic 2 failures in all 8 rounds. No flakiness or load-induced failures were observed in either sweep. Implementation storage remains in-memory only (no sqlite/file/`/tmp` persistence, no seeded entities), verified by grep.

## Step 8: Finalize PRD — 2026-09-03T03:48:00.000Z

(Recovered entry: this Step 8 record was first appended to `workspace/worklog.md` by mistake — a stray `cd` into `workspace/` left the shell there — and has been spliced back into position here verbatim. Nothing was overwritten or lost; the misplaced copy was removed.)

Orchestrator verification: `diff -q PRD.md PRD_FINALIZED.md` reports the files identical, matching the subagent's zero-edit claim. This is the expected shape of outcome given Step 7 made 0 implementation fixes and 0 deletions — both Step 7 items were test-local setup bugs the PRD itself adjudicated, so there was no PRD silence or mismatch to patch. `PRD_FINALIZED.md` exists (byte-identical) so Step 9 has a well-defined input.

Subagent summary (verbatim):

`PRD_FINALIZED.md` created as a **byte-identical copy** of `PRD.md`. **Zero edits.**

- Line counts: PRD.md 457 / PRD_FINALIZED.md 457 — **0.0% delta**; `diff` clean, identical md5 (`fd573f4b…`).
- Change bullets: none.

## Why no edit was warranted

Both `<step_7_diff>` items were test-local setup bugs; I verified each site against `implementation/` and found the PRD already uniquely determines the behavior.

### Site A — rung 24 (`ERR_INSUFFICIENT_CLAIM_HISTORY`) vs rung 25 (`ERR_VINTAGE_EXPOSURE_EXPIRED`) + maturity inputs

(a) **Subject:** accrual-create refusal ordering, and the inputs to `history_maturity_status` / `observed_exposure_units`.

(b) **Impl paths enumerated and read:**
- `implementation/routes/accruals.py:35-60` — the create ladder in source order: rung 9 stale version (39), rung 11 period closed (41), rung 21 no failure modes (45), rung 22 analog basis (47), rung 24 maturity (50), rung 25 exposure (52), rung 26 duplicate (54). Exactly PRD §2.9's rung numbering, so rung 24 legitimately pre-empts rung 25.
- `implementation/services/calc.py:121-148` (`history_maturity`) — `observed_history_months` = max `months_in_service_to` across all family observations else 0; `observed_exposure_units` = sum of `units_shipped` over vintages with `exposure_status` in `("ACTIVE","EXPIRED")`; `units_sold_lifetime` aliases it; `MATURE` iff `>=12` **and** `>=5000`. Verbatim PRD §3.2.
- All five re-derivation triggers, grepped for `apply_history_maturity`: family register `routes/catalog.py:64`, family update `:90`, vintage register `:152` (after `apply_exposure_status` at `:151`), claim-observation append `:295`, clock move `services/calc.py:704-706`. Matches PRD §3.2's stated trigger list, so `accruals.py:50` reading the *stored* status is not a hidden extra choice.
- `implementation/services/calc.py:102-115` (`compute_exposure_status`) — `ACTIVE` while clock strictly earlier than `warranty_expiry_date`. Matches §3.2. Also confirmed the `ACTIVE`/`EXPIRED` filter is duplicated identically in the `ANALOG_BLEND` analogue-exposure sum (`calc.py:275-279`) and in `ibnr_liability_reserve`'s floor via `units_sold_lifetime` (`calc.py:499`), so any prose touch here would have had to hold for those too.

(c) **Wording adjustment:** none — no sentence needed changing. §3.3's narrative mentions the exposure gate before the maturity gate, but §2.9 explicitly governs precedence ("Implementations must honour this ladder exactly"), and §3.3 makes no precedence claim, so this is not a mismatch to pin.

### Site B — §3.5 buffered build-window conflict / 30-day buffer / EXPIRED vintages in `observed_exposure_units`

(a) **Subject:** the `ERR_FIELD_ACTION_WINDOW_CONFLICT` geometry (buffer, endpoint inclusivity, candidate filter, family scope).

(b) **Impl paths enumerated and read:**
- `implementation/routes/field_actions.py:58-70` — `new_start <= existing_end + 30d and existing_start - 30d <= new_end`, character-for-character PRD §3.5's "Concretely, a conflict exists when…" sentence; buffer constant `calc.FIELD_ACTION_QUIET_BUFFER_DAYS = 30` (`services/calc.py:49`, bound at `field_actions.py:32`).
- Candidate filter `field_actions.py:61-64` — same `family_id` only, `approval_state` in `DRAFT`/`SUBMITTED`/`APPROVED`, `REJECTED` excluded. Matches §3.5.
- Check placement relative to the ladder: after shape (`:49-53`), after FK (`:54`), after `ERR_DUPLICATE_CODE` (`:55`) and before insert — consistent with §2.9 rungs 5/6/8/33 and with "nothing is persisted".
- Verified the buffer constant has no other consumer (grepped `FIELD_ACTION_QUIET_BUFFER_DAYS` / `BUFFER`): only this one site, so no parallel path could be mis-described.
- `observed_exposure_units` treatment of `EXPIRED` re-checked at `calc.py:127-131` (see Site A) — Step 7's 6000 assertion is what the PRD already states.

(c) **Wording adjustment:** none. The only arguably loose sentence in §3.5 is the "only a gap of 31 days or more is accepted" gloss; read as a date difference (`new_start - existing_end >= 31`) it agrees exactly with the pinned formula the impl implements, and the formula sentence is the determinative one. Rewriting the gloss would add risk without removing ambiguity, so I left §3.5 verbatim.

**Net:** the implementation was vindicated by the PRD on both counts, so per the "do not manufacture edits" guidance `PRD_FINALIZED.md` is unchanged from `PRD.md`.


## Step 9: Complete PRD — 2026-09-03T04:05:00.000Z

Orchestrator verification: `PRD_COMPLETED.md` is 457 lines / 112,523 chars against `PRD_FINALIZED.md`'s 457 lines / 104,467 chars (+8,056 chars of purely inline prose). `diff` of the heading sets is empty, so no section was added, removed or renamed; the §4 endpoint table still holds 59 rows and the §5 catalogue still holds 48 distinct `ERR_*` codes; the file ends on `| \`ERR_RESERVE_CAP_EXCEEDED\` | 422 |`, a real section boundary — no truncation. Step 9 touched neither `implementation/` nor the tests, so the Step 7 sweep artifacts (`results.{1..8}.json`, each 132/132) remain the valid evidence of a green suite.

Pipeline complete: `workspace/PRD_COMPLETED.md` exists, so Step 9's exit condition is satisfied.

Subagent summary (verbatim):

`PRD_COMPLETED.md` is written.

## Source vs output
- `PRD_FINALIZED.md`: 457 lines, 104,467 chars
- `PRD_COMPLETED.md`: 457 lines, 112,523 chars → **+8,056 chars**, line count unchanged, headings and all tables byte-identical, no new sections.

## Counts
- **31 changed passages** across 32 lines: **26 ambiguity-pins**, **5 mismatch-revisions**.

## Changes
- §2.1 — insert — ambiguity — an empty-string `X-User-ID`/`X-User-Role` is rejected like an absent one — `auth.py:24`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `response.py:9,19`
- §2.2 — insert — ambiguity — `api_request_timestamp` reads the real wall clock, not the logical clock — `response.py:22-24`
- §2.2 — insert — ambiguity — unrouted request → `ERR_INVALID_REQUEST`/404; undeclared method → `ERR_INVALID_REQUEST`/405 — `app.py:62-70`
- §2.3 — insert — ambiguity — `offset` has no maximum; non-integer `limit`/`offset` is a 400 — `validation.py:169-180`
- §2.3 — insert — ambiguity — filters match by exact string equality, empty-string filter = absent, unmatched value yields an empty page, undeclared query params ignored — `validation.py:188-192`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are wall-clock and `created_at` is strictly increasing (ordering = insertion order); derived figures written during creation leave `version` at 1 — `store.py:85-108`
- §2.5 — insert — ambiguity — `to_iso8601` is the only accepted field and the clock may move backwards — `clock.py:18-22`
- §2.9 r3 — insert — ambiguity — a `SupplierRep` naming an unresolvable recovery id falls through to rung 4's 404; the list read is refused before the query is examined — `suppliers.py:113-127,182-185`
- §2.9 r5 — insert — ambiguity — unparseable/non-object body is a 400, absent/empty body reads as `{}`, bodyless endpoints reject any field, ints reject bools/non-integers, strings reject `""` — `validation.py:71-160`
- §2.11 — revise — **mismatch** — cascade/recomputed rows are touched only when a stored value actually moves; the directly targeted row always is — `calc.py:211-230`, `accruals.py:180`
- §3.1 — revise — **mismatch** — `period_code` is validated only as a non-empty string; `YYYY-QN` is not enforced — `periods.py:26`
- §3.1 — revise — **mismatch** — the three disclosure counters are read-time derivations; approving a field action does not bump the period's `version`/`updated_at` — `serialize.py:18-36`
- §3.2 — insert — ambiguity — family PATCH: all fields optional, empty body legal and still a mutation, nulls clear, balance untouched — `catalog.py:73-92`
- §3.2 — revise — **mismatch** — `ship_period_code` is a non-empty string, shape unenforced and never resolved to a period — `catalog.py:127`
- §3.2 — insert — ambiguity — observation `failure_mode_id` need not belong to the cohort's family; effect on `paid_to_date_cents` vs the `HISTORICAL_RATE` mode loop — `catalog.py:262`, `calc.py:246`
- §3.3 — insert — ambiguity — accrual create computes the full estimate; new row's `version` is 1 — `accruals.py:80-82`
- §3.3 — insert — ambiguity — revise re-runs no arithmetic — `accruals.py:137-140`
- §3.3 — insert — ambiguity — the cap's hypothetical balance also drops the accrual it would supersede — `calc.py:169-177`
- §3.4 — insert — ambiguity — repeat reviews of a period-and-family pair are allowed and both true-ups count — `accruals.py:189`
- §3.4 — insert — ambiguity — re-applying a true-up answers `ERR_INVALID_STATE_TRANSITION` — `accruals.py:238`
- §3.5 — insert — ambiguity — `per_unit_expected_cents` computed at option creation; parent action untouched; option list is `created_at` asc, unfiltered — `field_actions.py:160-170`
- §3.5 — insert — ambiguity — an explicit null `remedy_option_id` is treated as omission — `field_actions.py:183`
- §3.5 — insert — ambiguity — select-remedy returns the field action, not the option — `field_actions.py:217`
- §3.5 — revise — **mismatch** — approval writes nothing into the period row — `field_actions.py:275-292`
- §3.5 — insert — ambiguity — only two execution hops are declared; `NOT_STARTED` target, `NOT_STARTED`→`COMPLETED`, or any call on `COMPLETED` answer `ERR_INVALID_STATE_TRANSITION`; `incurred_cost_cents` ≥ 0 — `field_actions.py:302-313`
- §3.6 — insert — ambiguity — a contract sold far enough in the logical past is created directly `EXPIRED` — `contracts.py:58-62`
- §3.7 — insert — ambiguity — `revised_asserted_amount_cents` minimum is 1 — `suppliers.py:152`
- §3.7 — insert — ambiguity — `response_note` required and non-empty; respond recomputes only `open_recovery_asset_cents` — `suppliers.py:186-196`
- §3.7 — insert — ambiguity — `settled_amount_cents` required (≥0) under `SETTLED`; booking-period check precedes the settlement-amount check — `suppliers.py:207-222`
- §3.7 — insert — ambiguity — write-off ignores any supplied amount and snapshots the pre-re-rating `collectability_rating_at_valuation` — `suppliers.py:233-237`
- §3.9 — insert — ambiguity — rollforward generation answers 201 with the snapshot in `data` — `periods.py:143`

Cross-checks that needed no change: all 48 error ids and HTTP statuses match `errors.py` exactly; all 59 endpoints and their authorized-role lists match the §4 table; every calculation in `calc.py` (13 of them) already matched the PRD's pinned rounding orders, clamp orders, thresholds and tie-breaks; the full 36-rung ladder ordering is honoured by the route bodies as written.
