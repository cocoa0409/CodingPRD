# Worklog — task_2280_elite_athlete_field_prize_purse

## Step 1: Create task directory — 2026-09-01T14:45:43.235Z

Created `tasks/task_2280_elite_athlete_field_prize_purse/` and `tasks/task_2280_elite_athlete_field_prize_purse/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T16:26:13.812Z

All three artifacts are complete and the linter is clean. Final verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2280_elite_athlete_field_prize_purse/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2280_elite_athlete_field_prize_purse/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2280_elite_athlete_field_prize_purse/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     13
  §1.8 instances scanned:     23
  §1.9 instances scanned:     39
  Calls scanned (§1.8+§1.9):  1289

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

**`SCAFFOLD.yaml`** (§1.0–§1.7, no design keys)
- Complexity profile: primary archetype `multi_party_negotiation`, secondary `pricing_engine`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `selector_policy`, `ops_run_checkpoint`; flat topology; parallel state-machine shape; `segregation_of_duties` role model; immediate consistency.
- **13 entities** (RaceEdition, PurseLine, DivisionStandard, Athlete, RepAgent, PerformanceRecord, Invitation, NegotiationRound `common_fields: false`, PacerAssignment, FluidStationSlot, DopingTest, RaceResult, PrizeAward), **6 state machines** (RaceResult is two parallel dimensions: certification + record claim), **2 §1.2.1 OCC rules**, **12 calculations** (2 dual-variant: package valuation, withholding), **16 ordered validations**, **50 endpoints**, **49 errors**, **6 roles**.

**`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — **9 rule_ids / 23 instances**, all with pre-computed literals and fully reachable setup chains: dual_variant_calc 2, combinatorial_formula 3 (modes a/b/c), non_linear_state_machine 2, transitive_cascade 2 (4-hop and 3-hop), priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 3 (closed-integer fluid slots, half-open km ranges, closed datetime windows), compensating_invariant 2.

**`SCAFFOLD_CORNER_DESIGN.yaml`** — **9 sections / 65 instances**: 39 full recipes + 26 `excluded_because` stubs, each citing an existing §1.8 instance by exact name. Per section: entities 12, state_machines 15, calculations 11, validations 9, endpoints 5, errors 3, rbac 3, cross_cutting_complexity_layers 6, consistency_model 1.

## Key findings
- **Error catalog fully triggerable**: all 49 error ids now appear in a §1.8/§1.9 assert (verified programmatically); the last 12 were swept by the `errors` and `endpoints` sections.
- **Two consistency fixes to SCAFFOLD.yaml** were needed because `ERR_RECORD_CLAIM_NOT_ELIGIBLE` (priority 15) was permanently shadowed by `ERR_INVALID_RECORD_CLAIM_STATE` (priority 8) — a SUB_ELITE result always has `record_claim_status: NONE`, so the state error fired first and the 422 was unreachable. The §1.6 conditions for both errors and the §1.2 precondition line were sharpened so state = {SUBMITTED, RATIFIED} → 409 and eligibility = {SUB_ELITE, never-raised NONE} → 422 are disjoint.
- Lint rule (e) rejects literal OCC versions: both `optimistic_concurrency` instances now derive their deliberately-stale value from a captured create-response `$.data.version` rather than a hardcoded `1`.
- Names are unique across §1.8 ∪ §1.9 (88 total, 0 duplicates); every §1.9 instance carries exactly one of `test_recipe` / `excluded_because`.
- The no-peeking constraint was honored: no sibling `tasks/task_*/` directory was listed, read, or searched.

## Step 3: Copy shared files — 2026-09-01T16:26:13.812Z

Copied `INSTRUCTION.md` → `tasks/task_2280_elite_athlete_field_prize_purse/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:36:00.000Z

PRD generated at `workspace/PRD.md` — 389 lines. I did not open either `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`, and no sibling task directory.

## Structure

**§1 Introduction** — 3 paragraphs framed around the committee's real operating problem (money promised before it is owed), the immediate-consistency requirement, and the two structural constraints (alternating negotiation, segregation of duties).

**§2 Global Specifications** — 11 domain-derived subsections: 2.1 RBAC (6 roles + all `identity:` translations), 2.2 API Response Structure (verbatim, byte-verified), 2.3 Pagination, 2.4 The Logical Race Clock, 2.5 Common Resource Properties, 2.6 Edition Posture as the Master Gate, 2.7 Stale-Version Protection on Superseding Writes, 2.8 Money/Basis Points/Rounding Discipline, 2.9 The Appearance Budget and Prize Purse Ledgers (INV-1/INV-2), 2.10 Cascades/Path Resolution/Existence, 2.11 Validation Precedence (all 16 priorities as an ordered list with error IDs, HTTP statuses and full `applies_to` enumerations).

**§3 Business Logic** — 9 subsections grouped by lifecycle timeline: 3.1 Standing Up an Edition, 3.2 Athletes/Agents/Time Verification, 3.3 Recruitment and the Negotiation Cycle, 3.4 Acceptance/Refusal/Withdrawal/Locking the Field, 3.5 Elite Athlete Services (bibs, fluid tables, pacing), 3.6 Anti-Doping and the Disqualification Cascade, 3.7 Race Day/Results/Certification/Course Records, 3.8 The Prize Purse, 3.9 The Ops-Run Checkpoint.

**§4** 50-row endpoint table, exactly 4 columns. **§5** 49-row error table, exactly 2 columns. Document ends at §5 with no audit footer.

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 114 required, 114 present, 0 missing
- endpoints[].request_body: 79 required, 79 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 16 checked, 16 expressed in prose (ordered list in §2.11), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_invitation_version / expected_race_edition_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 38 checked (RaceEdition 5, Invitation 14, PerformanceRecord 2, DopingTest 4, RaceResult 7, PrizeAward 5, plus the system CLAIMED→REJECTED cascade), 38 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 16 checked, all 49 error IDs matchable to a trigger condition in §2 or §3 prose, 0 missing
- endpoints[].side_effects / applies_to: 50 endpoints checked, all side-effect lists expressed in narrative, 0 missing
- entities[].fields[] structured content: 114 checked (types, defaults, constraints, initial values, read-only derivations), 114 reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (OFFERED/COUNTERED → ACCEPTED; OFFERED/COUNTERED → DECLINED; DRAFT/OFFERED/COUNTERED vs ACCEPTED → WITHDRAWN; PROVISIONAL vs CERTIFIED → DISQUALIFIED; verification VERIFIED/REJECTED; adjudication CLEARED/ADVERSE; record-decision RATIFIED/REJECTED; withholding PER_AWARD/AGGREGATED), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 712
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verifications: §2.2 matches the canonical source byte-for-byte (including `req_RANDOMALPHANUM123456` and `"data": { }`); all 6 state enumerations and every enum member appear verbatim; no fuzzy/approximating words present; every scaffold constant is embedded in business context, including the otherwise-unused 90-day out-of-competition clearance horizon (marked explicitly informational to avoid inventing a gate) and the 42.195 km course length used as context for the 32.0 km pacing ceiling.

## Step 5: Generate unit tests — 2026-09-01T18:05:29.000Z

Suite is complete and machine-verified. Final state:

## Files

**`test_helpers/`** (infrastructure, 9 modules): `__init__.py` (barrel re-exporting the framework generics plus every local helper), `api_client.py` (one method per PRD §4 endpoint), `fixtures.py` (clock control, per-entity wrappers, and the composite builders `setup_configured_edition` → `setup_field_open_edition` → `setup_raced_edition` → `setup_edition_with_certified_results` → `setup_edition_with_computed_awards` → `setup_paid_award`), `factories.py`, `assertions.py` (`assert_common_fields`, `assert_purse_ledger`, `assert_appearance_ledger`), `test_users.py`, `api_errors.py` (all 51 §5 codes), `constants.py`, `types.py`.

**`test_suite/`**: `conftest.py` + 15 test modules, **124 tests, all collecting cleanly** (`pytest --collect-only` → 124).

| Queue | Files | Tests | Instances |
|---|---|---|---|
| A (Difficulty §1.8) | test_01…test_07 | 60 | 23/23, every instance ≥2 tests |
| B (Corner §1.9) | test_08…test_15 | 64 | 39/39 non-stub (entities 12, state_machines 8, calculations 3, validations 4, endpoints 3, errors 3, rbac 2, cross_cutting_layers 3, consistency_model 1) |

Per-file: 8, 5, 5, 8, 8, 10, 16 | 12, 12, 8, 7, 7, 6, 4, 8.

## Verification

- `pyflakes` over `test_suite/` → clean (only the intentional barrel re-export warnings in `test_helpers/__init__.py`).
- AST audit: exactly one `Design:` line per test, always the last docstring line, zero dangling tags, zero section mismatches, zero tests tagging one of the 26 `excluded_because:` stubs, no `pytest.mark.skip`/`xfail` anywhere, no "scaffold" or design-document wording in any comment.
- AST citation checker: every quoted span ≥20 chars occurs **exactly once** in `PRD.md` after whitespace normalisation → `quote problems 0`. This pass fixed 13 pre-existing citation defects across test_01/02/04/07/08 where quotes had been abbreviated with `...` or had drifted in leading capitalisation/terminal punctuation; each was replaced with the contiguous full clause.

## Instances skipped

**None.** Every non-stub instance in both indices is translated. Where a design recipe asserted an outcome the PRD does not derive, the assertion was re-derived from the PRD rather than the instance being weakened or dropped:

1. **§3.4 `guaranteed_commitment_cents` on non-`ACCEPTED` invitations** — four instances (`cross_entity_offer_blocked_until_performance_record_verified`, `corner_invitation_computed_fields_seeded_then_derived_from_offer`, `corner_offer_side_effects_stamp_deadline_round_and_negotiator`, `corner_error_qualifying_standard_missing_and_performance_division_mismatch`) assert non-zero commitments (684,000 / 1,406,000 / 1,554,000 / 584,000) on `OFFERED` invitations; the PRD says it "reads as zero" in every status other than `ACCEPTED`. Asserted 0 plus the `current_appearance_fee_cents` mirror. `full_exposure_cents` likewise asserted 0 before field lock.
2. **`corner_consistency_immediate_...`** glosses BUSINESS air as 300,000 and ground as 30,000 (PRD: 540,000 / 18,000) and asserts 1,958,000 / 4,458,000 with `round_count == 0`. Asserted the PRD arithmetic: `ACCEPTED` commitment **2,186,000** (1,500,000 + 540,000 + 4×32,000 + 18,000), edition uncommitted **6,814,000**, and `round_count == 1` because sending the offer writes round 1.
3. **`corner_layer_occ_stale_invitation_version_...`** assumes the offer writes no round, so its `round_number` 1/2 and `total_count == 0` were re-derived to 2/3 and a 3-row history (offer + two accepted appends).
4. **`corner_rbac_peer_agents_...`** — same off-by-one; asserted `round_number == 2` and one `side=AGENT` row.
5. **Pacing precedence claim** (32.0 km ceiling vs overlap ordering) is not uniquely derivable; asserted only the error id and status.
6. **`PURSE_COMPUTED`** is not one of the six §2.6 postures, so `boundary_empty_award_set_...` asserts HTTP 200 + `RESULTS_CERTIFIED`.
7. **`corner_double_certify_race_result_rejected_as_non_idempotent`** — the PRD names no error id for re-certifying a `CERTIFIED` result, so only HTTP 409 is asserted.
8. **`corner_endpoint_settle_purse_action_endpoint_preconditions` trigger 6** expects `ERR_AWARDS_NOT_ALL_SETTLED` for settling before any award exists; §3.8 makes that condition vacuously true with zero awards, so that single step was omitted (the instance is still covered by three tests).

## Step 6: Generate implementation — 2026-09-01T17:05:44.000Z

Implementation complete and validated.

## Files created (28) — all under `workspace/implementation/`

Launcher / deps: `start.sh` (guarded `import flask` check, then `exec python3 app.py`), `requirements.txt` (Flask==3.0.3)

Core: `app.py` (blueprint registration, global request lock, `ApiError`/404/405/HTTPException/Exception handlers, `0.0.0.0:$PORT` default 10000), `db.py` (13 in-memory collections, `_seq` insertion counter), `errors.py` (49-code catalog → HTTP status), `clock.py` (logical clock pinned to `2026-08-01T00:00:00Z`; wall clock never read), `response.py` (meta envelope + pagination), `constants.py`, `middleware.py` (header auth + role gate), `validators.py`

Routes (10): `editions.py`, `config.py`, `people.py`, `invitations.py`, `elite_services.py`, `doping.py`, `results.py`, `awards.py`, `clock_route.py`, `__init__.py`

Services (8): `lookup.py`, `serializers.py`, `gates.py`, `valuation.py`, `places.py`, `awards.py`, `cascade.py`, `__init__.py`

## Endpoints: 50

Registered route inventory diffed 1:1 against the PRD §4 table — exact match, no extras, none missing.

## Verification

Five throwaway smoke suites (since deleted; nothing written into the task tree outside `implementation/`) exercised the full lifecycle plus error paths, all passing: guaranteed valuation with the 7-night cap, tie pooling with the remainder cent to the earliest result, wheelchair 7500-bps floored bonus, PER_AWARD vs AGGREGATED de-minimis withholding, largest-remainder split (75,000 → 60,000 / 15,000), masters age boundary (birthday on race day counts), OCC 412s, turn-taking 403s, round exhaustion, appearance-budget and field-lock-exposure ceilings, bib pool exhaustion, doping window overlap / frequency cap, DQ + breach + clawback cascade, ADVERSE four-hop cascade (result DISQUALIFIED, claim REJECTED, award VOID, invitation BREACHED, ledger back to zero), record ratification overwriting the course record, run-ops expiry + missed-test tally, settlement gating, and post-`PURSE_SETTLED` subtree rejection. Fresh boot from `start.sh` serves an empty store (`total_count: 0` on every list) — no seeded entities.

## PRD ambiguities resolved by choice

- **Undeclared error codes.** `ERR_RESULT_NOT_CERTIFIED` (409) for certify/disqualify from a disallowed result state; `ERR_INVALID_INVITATION_STATE` (409) for lock-field with zero ACCEPTED invitations and for withdrawing an ACCEPTED invitation that already has a result; `ERR_INVALID_RECORD_CLAIM_STATE` (409) for settle-purse blocked by a SUBMITTED claim.
- **Precedence over prose order.** §2.11's 16-level precedence was treated as authoritative wherever §3 prose listed checks in a different order — notably assign-bib checks doping compliance (priority 12) *before* `ERR_BIB_ALREADY_ASSIGNED` (14), and offer validation runs suspended-agent (12) → standard missing/not-met (14) → division mismatch (15).
- **Ordering within priority 14** for doping-test scheduling: window overlap → frequency cap → `sample_code` uniqueness.
- **Endpoints absent from the §2.6 posture map** (run-ops, record-submission, record-decision, all doping-test endpoints) get only the blanket `PURSE_SETTLED` rejection.
- **Fluid-station slots** do not require the invitation to be ACCEPTED (no error code is declared for that case).
- **Derived fields** (ledger projections, `round_count`, `occupied_from/to`, `guaranteed_commitment_cents` reading zero outside ACCEPTED) are computed at serialization time; `version` bumps still occur only at PRD-declared points.
- **Stable list ordering** is `(created_at, _seq)` because the logical clock makes `created_at` collide.
- **ADVERSE cascade** breaches the invitation for every result it disqualifies, including PROVISIONAL ones; a *manual* disqualify from PROVISIONAL records status + reason only, per §3.7.
- **Record ratification** hop 3 re-checks all CLAIMED CERTIFIED results of the edition with no gender/record-class filter.
- **Misc:** enum-valued list filters are validated (400); pagination validation runs after existence so a list under a missing parent is 404; `AthleteAgent` is deliberately not authorized on `POST /_clock/set_current_utc`; country codes are only checked non-empty (no ISO format validation) to avoid false rejections.

## Step 7: Run tests and iterate — 2026-09-02T06:20:50.000Z

All 8 rounds of the mandated `prd-bench-local-run --isolation per-test-server` sweep are green: **124/124 passed in every round**, zero failures. Exit condition met.

## Summary

**Iterations run: 2 fix iterations, 4 completed 8-round sweeps (plus 1 independent cross-check sweep)**

- **Iteration 1** — 8-round parallel sweep. Union of failures across the 8 rounds = 2 distinct tests, both failing in all 8 rounds (deterministic, not flaky). Diagnosed and fixed both.
- **Iteration 2** — confirming sweeps. Every remaining failure was a harness artifact, never a test/implementation failure: `subprocess.TimeoutExpired` on the runner's own port cleanup (`pids=$(lsof -ti:PORT -sTCP:LISTEN)`, hardcoded `timeout=5` in `prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py:52-56`). The host was shared with 380–520 concurrent runner processes and load averages of 200–450 on 32 cores, so `lsof` regularly exceeded its 5 s budget. Across ~30 sweep rounds I classified 100% of failures as infrastructure and **0 real failures**. The final sweep completed once host load fell to ~110.

**Tests deleted: none.** No test hit a PRD-silence or non-derivability collapse pattern; both defects were genuine bugs traceable to verbatim PRD sentences.

**Fixes applied to `test_helpers/`: none.**

**Fixes applied to `test_suite/`:**
- `test_suite/test_09_posture_and_state_machines.py` — helper `_edition_awaiting_its_ops_sweep()` (line ~499). It stored the value returned by `agent_counters(...)` into `countered["invitation"]`, but per PRD §4 ("Operations that bring a new resource into existence return `201 Created`: … a negotiation round …") and §2.2, `POST /invitations/{id}/negotiation-rounds` returns the **NegotiationRound**, not the invitation. The later `read_invitation(...)` therefore used a round id and got 404 `ERR_INVITATION_NOT_FOUND`. Now calls `agent_counters(...)` for its side effect and re-reads the invitation by its own id. TEST BUG; the fix makes the fixture more PRD-faithful.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/results.py` — `record_submission()`. The certification-status precondition was folded into the priority-15 eligibility branch, so a DISQUALIFIED result with claim `REJECTED` returned `ERR_RECORD_CLAIM_NOT_ELIGIBLE` (422). PRD §2.11 ranks "target entity state … `ERR_RESULT_NOT_CERTIFIED` (409)" at priority 8, ahead of the priority-15 cross-entity coherence rule "a record package may only be lodged for a non-`SUB_ELITE` result whose claim status is `CLAIMED` or `REJECTED`, else `ERR_RECORD_CLAIM_NOT_ELIGIBLE`". Split into a priority-8 `ERR_RESULT_NOT_CERTIFIED` check followed by the priority-15 division/claim-eligibility check; the pre-existing `SUBMITTED`/`RATIFIED` → `ERR_INVALID_RECORD_CLAIM_STATE` guard still precedes both.

No assertions were weakened, no skips/xfails added, no endpoints/fields/side effects added, and storage remains in-memory dicts with no startup seeding.

Supporting evidence beyond the mandated sweep: an independent harness (fresh server per test on a private port, bypassing the runner's port cleanup) ran the suite 8 times **concurrently** plus once sequentially — 124/124 in all 9 runs, confirming no timing-sensitive flakiness in the suite or implementation.

## Step 8: Finalize PRD — 2026-09-02T06:28:26.000Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 388 lines; PRD_FINALIZED.md: 388 lines; **0.0% line delta** (one paragraph extended in place, +4 sentences / +~730 chars inside §3.7's existing paragraph).

## Changes
- **§3.7 (record-claim dimension, record-submission preconditions)** — *insert* — pinned the intra-endpoint evaluation order of the three lodging preconditions: (1) claim already `SUBMITTED`/`RATIFIED` → `ERR_INVALID_RECORD_CLAIM_STATE` first, irrespective of certification status and division; (2) any `certification_status` other than `CERTIFIED` (incl. `PROVISIONAL` and `DISQUALIFIED`) → `ERR_RESULT_NOT_CERTIFIED` as the priority-8 error, irrespective of division and of whether the claim is `NONE`/`CLAIMED`/`REJECTED`; (3) only a `CERTIFIED` result reaches the priority-15 `SUB_ELITE`-or-`NONE` → `ERR_RECORD_CLAIM_NOT_ELIGIBLE` test — `implementation/routes/results.py:174-193`.

The PRD already named the code for the claim-state case and already ranked the two priorities, but it never named **which** code a non-`CERTIFIED` result gets at lodging, nor the order between the two same-priority-8 checks; that is exactly the ambiguity the Step 7 implementation fix resolved.

**No PRD edit for the two non-impl Step 7 items.** The `test_suite/test_09` fixture fix (treating the `POST /invitations/{id}/negotiation-rounds` body as the invitation) is a pure fixture bug: §4 ("a negotiation round" returns `201 Created`) plus §2.2 already determine that the round is returned, and `routes/invitations.py:252` returns `ser_round(rnd), 201` — PRD stays verbatim. No `test_helpers/`/`test_suite/` silences and no deletions to trace.

## Per-edit pre-edit search log
**Edit 1 — §3.7 lodging precondition order**
- (a) Subject: the record-submission precondition set and the error codes `ERR_RESULT_NOT_CERTIFIED`, `ERR_INVALID_RECORD_CLAIM_STATE`, `ERR_RECORD_CLAIM_NOT_ELIGIBLE`, plus every other consumer of a result's `certification_status`/`record_claim_status`.
- (b) Paths enumerated (grepped `ERR_RESULT_NOT_CERTIFIED|ERR_INVALID_RECORD_CLAIM_STATE|ERR_RECORD_CLAIM_NOT_ELIGIBLE|record_claim_status|certification_status` across all of `implementation/`, then read each hit):
  - `routes/results.py:164-198` `record_submission` (the Step 7 site) — order: posture gate → claim `SUBMITTED`/`RATIFIED` → cert → division/claim eligibility.
  - `routes/results.py:123-139` `certify_result` — non-`PROVISIONAL` also raises `ERR_RESULT_NOT_CERTIFIED`.
  - `routes/results.py:142-161` `disqualify_result` — non-`PROVISIONAL`/`CERTIFIED` also raises `ERR_RESULT_NOT_CERTIFIED`.
  - `routes/results.py:201-229` `record_decision` — non-`SUBMITTED` claim **and** `RATIFIED`-on-non-`CERTIFIED` both raise `ERR_INVALID_RECORD_CLAIM_STATE`, *not* `ERR_RESULT_NOT_CERTIFIED`.
  - `routes/awards.py:47-76` `approve_award` — result not `CERTIFIED` → `ERR_RESULT_NOT_CERTIFIED` (after `ERR_INVALID_AWARD_STATE`).
  - `routes/editions.py:210-230` `settle_purse` — claim `SUBMITTED` → `ERR_INVALID_RECORD_CLAIM_STATE`.
  - `routes/editions.py:172-186` `certify-results` (raises `NONE → CLAIMED` only for non-`SUB_ELITE`), `services/cascade.py:26-97` (disqualify sets `CLAIMED`/`SUBMITTED → REJECTED`; `ratify_record` rejects weaker `CLAIMED` claims), `services/awards.py:139`, `services/places.py:48`, `services/serializers.py:233-234`, `services/gates.py:11-26` (`gate_edition(edition)` with no allow-list = any posture but `PURSE_SETTLED`).
- (c) Wording adjustments made to stay consistent with all of the above: scoped every clause to this endpoint ("at this endpoint", "A package lodged against…") so the new sentences do **not** claim `ERR_RESULT_NOT_CERTIFIED` is the universal code for a non-`CERTIFIED` result — that would have contradicted `record_decision`'s `ERR_INVALID_RECORD_CLAIM_STATE` on ratification and misdescribed `certify_result`/`disqualify_result`, whose own uses of the code cover different state sets. Enumerated the reachable claim values (`NONE`, `CLAIMED`, `REJECTED`) rather than saying "any claim status", since `SUBMITTED`/`RATIFIED` are already consumed by the earlier check. Left the pre-existing §2.11 precedence-note paragraph and the §3.7 sentences before the insert verbatim, as the implementation matches them exactly. Deliberately did **not** touch the posture-gate wording (`gate_edition` allowing every posture but `PURSE_SETTLED` here) — that path was not a Step 7 site and is out of the hard scope.

## Step 9: Complete PRD — 2026-09-02T06:38:50.000Z

**Files** — source `workspace/PRD_FINALIZED.md`: 388 lines / 86,916 chars. Output `workspace/PRD_COMPLETED.md`: 389 lines / 95,296 chars (**+1 line, +8,380 chars**, 35 diff hunks, no section added).

**Counts** — 36 edits: **31 ambiguity-pins**, **5 mismatch-revisions**.

Per change (`{section} — {kind} — {type} — {what} — {impl}`):

- §2.2 — revise — ambiguity — `api_request_timestamp` comes from the logical clock, not real time — `response.py:24`
- §2.2 — insert — mismatch — unrouted path / wrong method answer `ERR_INVALID_REQUEST` at HTTP 404/405, not the catalogue's 400 — `app.py:65-71`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` are 400; out-of-enum filter values are 400; identifier filters are never existence-checked (empty page, no 404) — `validators.py:130-159`, `routes/invitations.py:163`
- §2.6 — revise — ambiguity — doping scheduling/collection/adjudication, record submission, record decision and run-ops are admitted from every posture except `PURSE_SETTLED` — `services/gates.py:11-21`, `routes/doping.py:55`, `routes/results.py:172`
- §3.1 — revise — ambiguity — `bib_range_end` >= 1 with no upper bound — `routes/config.py:86`
- §3.1 — revise — ambiguity — `threshold_seconds` strictly > 0 — `routes/config.py:44`
- §3.2 — insert — ambiguity — `country_code`/`tax_residency_country` only checked non-empty, never against ISO — `routes/people.py:32,35`
- §3.2 — revise — ambiguity — tax-profile fields all optional, null == omitted, `version` bumps even on an empty body — `routes/people.py:69-78`
- §3.2 — revise — ambiguity — `rejection_reason` is a `PerformanceRecord` response field, null until rejection — `services/serializers.py:133`
- §3.3 — revise — ambiguity — offer requires `DRAFT` (`ERR_INVALID_INVITATION_STATE`) ahead of agent/qualifying gates; standard-existence tested before the record's own state/time/window/chip; coherence (p15) last — `routes/invitations.py:189`, `services/gates.py:91-122`
- §3.3 — insert — mismatch — offer answers 200 with the invitation despite creating round 1 — `routes/invitations.py:209`
- §3.3 — insert — ambiguity — append answers 201 with the round object and its exact field list — `routes/invitations.py:252`, `services/serializers.py:162-175`
- §3.4 — revise — ambiguity — respond requires `OFFERED`/`COUNTERED` (`ERR_INVALID_INVITATION_STATE`) before turn-taking — `routes/invitations.py:282`
- §3.4 — revise — ambiguity — `DECLINE` does not touch the edition; both decisions answer 200 with the invitation — `routes/invitations.py:291-294`
- §3.4 — revise — mismatch — withdraw `reason` is validated but not persisted; only four statuses withdrawable; the race-result block is `ERR_INVALID_INVITATION_STATE` — `routes/invitations.py:315-326`
- §3.4 — revise — ambiguity — lock with no `ACCEPTED` invitation is `ERR_INVALID_INVITATION_STATE`, before the exposure ceiling — `routes/editions.py:120-124`
- §3.4 — insert — ambiguity — lock bumps the edition `version` exactly once — `routes/editions.py:147`
- §3.5 — insert — ambiguity — doping gate (p12) precedes the already-assigned check (p14) — `routes/invitations.py:350-353`
- §3.5 — revise — ambiguity — a missing division standard yields `ERR_BIB_POOL_EXHAUSTED` — `routes/invitations.py:363-369`
- §3.5 — insert — mismatch — the slot endpoint imposes no invitation-status precondition — `routes/elite_services.py:30-49`
- §3.5 — revise — ambiguity — pacing ceiling tested before the overlap check — `routes/elite_services.py:96-107`
- §3.6 — revise — ambiguity — window timestamps accept Z/offset/naive and echo back normalised 3-digit UTC — `routes/doping.py:92-93`, `clock.py:43-57`
- §3.6 — insert — ambiguity — both capacity rules scan across all editions; the 7-day span is inclusive; order is overlap → frequency → `sample_code` — `routes/doping.py:57-86`
- §3.6 — insert — ambiguity — the edition `version` moves at most once and only if an award moved or an invitation breached — `routes/doping.py:186-189`, `services/cascade.py:40-56`
- §3.7 — revise — ambiguity — certifying a non-`PROVISIONAL` result and disqualifying an already-`DISQUALIFIED` one both give `ERR_RESULT_NOT_CERTIFIED` — `routes/results.py:132-156`
- §3.7 — revise — ambiguity — DQ edition `version` bump is conditional on an award moving or a breach — `services/cascade.py:40-56`, `routes/results.py:158-160`
- §3.7 — insert — ambiguity — the places pass touches only results whose five computed fields actually change — `services/places.py:34-39`
- §3.7 — revise — mismatch — `decision_note` is validated but not persisted; a `REJECTED` decision does not touch the edition — `routes/results.py:207,223-226`
- §3.8 — revise — ambiguity — same-place partitions visited by ascending division (null first) then gender, fixing award creation/list order — `services/awards.py:88-91`
- §3.8 — revise — ambiguity — one edition `version` bump per run; the run answers 200 with the edition, not the award set — `routes/editions.py:205-207`
- §3.8 — revise — ambiguity — award-state check precedes the result-certification check on approval — `routes/awards.py:56-64`
- §3.8 — revise — ambiguity — a still-`SUBMITTED` claim blocks settlement with `ERR_INVALID_RECORD_CLAIM_STATE`, evaluated after the award sweep — `routes/editions.py:216-227`
- §3.9 — insert — ambiguity — run-ops admitted from every posture but `PURSE_SETTLED`, answers 200 with the edition — `routes/editions.py:238`
- §3.9 — revise — mismatch — step two is scoped to the swept edition's own doping tests — `routes/editions.py:254`
- §3.9 — revise — ambiguity — step three's ledger recompute and compliance re-evaluation persist nothing; only the version bump is visible — `routes/editions.py:265-267`, `services/serializers.py:16-34`
- §4 — revise — ambiguity — which resource each 200 transition returns, and the clock's `{"current_utc": …}` payload with required `to_iso8601` — `routes/clock_route.py:21-24`

Cross-check: every `ERR_*` raise site in `implementation/` now maps to explicit PRD prose.
