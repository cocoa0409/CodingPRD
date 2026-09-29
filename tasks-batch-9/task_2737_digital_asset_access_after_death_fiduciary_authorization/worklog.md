# Worklog — task_2737_digital_asset_access_after_death_fiduciary_authorization

## Step 1: Create task directory — 2026-09-04T13:48:46.696Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2737_digital_asset_access_after_death_fiduciary_authorization` and its `workspace/` subdirectory. Index 2737 was pre-assigned by the invoker; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T15:27:26.930Z

All three scaffold artifacts for task_2737 are complete and lint-clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2737_digital_asset_access_after_death_fiduciary_authorization/`
- `SCAFFOLD.yaml` — 4,482 lines (§1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 3,051 lines (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,623 lines (single key `scaffold_corner_design`)

All three parse with `yaml.safe_load`.

## Scaffold contents (§1.0–§1.7)
- 14 entities, flat topology, `parallel` state-machine shape, `segregation_of_duties` role model, `immediate` consistency, layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation
- 8 state machines (Document, PlatformRequest, DigitalAsset with independent access/disposition dimensions, AuthorityGrant, DispositionElection, CancellationOrder, RefundClaim, Estate)
- 8 calculations (authority precedence ladder, disclosure level, transferability first-match chain, appraisal with per-category alternate decay, valuation rollup with tiered deduction cap, floor-then-remainder allocation plan, refund entitlement in two methods, administration phase)
- 72 validations, 53 endpoints, 68 errors, 4 roles, 2 OCC concurrency rules

## Design instances
- §1.8: 9 rule blocks / 25 instances
- §1.9: 48 instances across all 9 taxonomy sections — entities 9, state_machines 13, calculations 8, validations 4, endpoints 2, errors 3, rbac 3, cross-cutting complexity layers 5, consistency model 1. 41 are full recipes; 7 are `excluded_because` stubs, each citing a §1.8 instance name that resolves.

## Verification
- Every one of the 68 declared error ids is triggered or cited in the two design files.
- No duplicate instance names across the union of both design files; no non-schema keys; no stub carries a `test_recipe`.
- Forbidden concurrency vocabulary: zero hits in all three files.
- Lint verdict (verbatim):

```
Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     41
  Calls scanned (§1.8+§1.9):  1277

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Notable corners captured this pass: the close-guard ladder refusing one blocker at a time (67→68→71→72→CLOSED); `ERR_COURT_ORDER_REQUIRED` distinguished from `ERR_CONTENT_DISCLOSURE_NOT_AUTHORIZED` by pre-clamp scope; an ALTERNATE run shrinking the pool below the already-distributed amount so priority 65 pre-empts 66; the live authority projection versus the scope frozen on the grant at APPROVE; and transferability recomputed only on an explicit review, where one `supports_transfer: false` flag yields `PROVIDER_NO_TRANSFER` for CLOUD_STORAGE but `PROVIDER_LICENCE_TERMINATES` for LOYALTY_PROGRAM.

## Step 3: Copy shared files — 2026-09-04T15:27:41.429Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T15:45:00.000Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **450 lines** (101,649 chars), ends at the final row of the §5 error table (no audit footer, no truncation).

**Section list**
- `# Digital Estate Fiduciary Access API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 Actors and Role-Based Access Control · 2.2 API Response Structure (verbatim contract, diffed byte-for-byte against `section-2.2-response-structure.md`) · 2.3 Pagination, Sorting and Collection Filters · 2.4 Common Resource Properties and Record Versioning · 2.5 The Logical Clock and Date Arithmetic · 2.6 Flat Addressing and Left-to-Right Path Resolution · 2.7 The Order of Rejection · 2.8 Optimistic Concurrency on Parent Records · 2.9 Money, Basis Points, Counts and Rounding Discipline · 2.10 Cascades, Derived Counters and Ledger Invariants
- `## 3. Business Logic & Workflows` — 3.1 Registering Providers and Opening the Estate File · 3.2 Appointing Fiduciaries, the Evidentiary Record, and the Administration Phase · 3.3 Recording Authority Directives and Resolving the Precedence Ladder · 3.4 The Inventory: Two Independent Postures and the Transferability Chain · 3.5 The Request Package and the Provider's Review Cycle · 3.6 Approval, the Content Clamp, and the Three Ways Authority Collapses · 3.7 Stopping the Charges and Chasing the Money Back · 3.8 Putting a Number on the Estate and Dividing It · 3.9 Electing a Disposition, Executing It, and Closing the File
- `## 4. API Endpoints` (4-column table, 53 rows)
- `## 5. Error Codes` (2-column table, 68 rows)

**Coverage:** 14 entities · 53 endpoints · 8 state machines / 50 transitions (including `DigitalAsset`'s two parallel dimensions and the compound `Estate` phase) · 8 calculations (`platform_authority_precedence`, `asset_disclosure_level`, `asset_transferability_class`, `asset_appraised_value`, `estate_valuation_rollup`, `beneficiary_allocation_plan`, `refund_entitlement`, `estate_administration_phase`) · 72 validations (as the 10-band ladder in §2.7 plus per-workflow prose in §3) · 2 OCC concurrency rules · 68 error codes.

**Hard Contract 1 — Field-Name Coverage: PASS.** Required set built mechanically from the scaffold (143 entity field names ∪ endpoint `input`/`output` identifiers = 152 names); diffed against backticked tokens in the PRD with code fences excluded — **0 missing**.

**Hard Contract 2 — Rule Coverage: PASS.** All 50 state transitions documented with triggers, preconditions and side effects; both OCC rules stated in §2.8 with write endpoint, `expected_estate_version` / `expected_asset_version`, `ERR_STALE_ESTATE_VERSION` / `ERR_STALE_ASSET_VERSION` and HTTP 412; the four-hop approval cascade, the depth-4 letters-revocation cascade with its conditional hop 2, the three grant-collapse paths with their distinct `revocation_reason` values, both transfer/reversal compensations, all `applies_to` scopes as the §2.7 ladder plus the three named priority-conflict pairs, and all field-level types/defaults/initial values. Every one of the 72 validations' `error_id`s is referenced somewhere in §1–§4, not just in the §5 table (verified mechanically). Sibling-branch symmetry given equal density for the two valuation bases, the two refund methods, and the three EXECUTE branches.

**Hard Contract 3 — §3 Path Purity: PASS (with one noted enum collision).** 344 distinct backtick tokens in §3; zero start with `/`, zero contain `/`, zero are method+path combinations. One token, `` `DELETE` ``, matches an HTTP-method spelling — it is the scaffold's `DispositionElection.election` enum value (alongside `MEMORIALIZE` and `TRANSFER`) and is required verbatim by Contract 2. The API defines no DELETE-method endpoint at all (only POST, GET and PATCH), so there is no ambiguity.

Both withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator truncation check (per invoker instruction):** `tail -25 PRD.md` confirms the file ends with `| \`ERR_OPEN_REFUND_CLAIMS\` | 409 |` — a complete final table row at a real section boundary, not mid-sentence. All 5 top-level sections and all 26 sub-headings present. No regeneration needed.

## Step 6: Generate implementation — 2026-09-04T16:23:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first, so its entry is recorded first. Step 5's entry follows below.)

Implementation complete.

## Files emitted (all under `workspace/implementation/`)

| File | Lines |
| --- | --- |
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 81 |
| `errors.py` | 98 |
| `clock.py` | 101 |
| `response.py` | 51 |
| `db.py` | 72 |
| `validation.py` | 170 |
| `authz.py` | 60 |
| `money.py` | 16 |
| `services/lookup.py` | 178 |
| `services/estate.py` | 110 |
| `services/authority.py` | 240 |
| `services/valuation.py` | 152 |
| `services/refund.py` | 15 |
| `routes/common.py` | 13 |
| `routes/system.py` | 18 |
| `routes/platforms.py` | 95 |
| `routes/estates.py` | 184 |
| `routes/paperwork.py` | 268 |
| `routes/assets.py` | 179 |
| `routes/requests.py` | 321 |
| `routes/dispositions.py` | 334 |
| `routes/refunds.py` | 332 |
| `routes/valuations.py` | 90 |

3189 lines total; every `.py` byte-compiles cleanly. `__pycache__` removed; no JSON/SQLite/`/tmp` artifacts — storage is pure in-memory dicts (`db.Store`) with zero seeded entities.

## Endpoints

All **53** routes in the PRD §4 table are registered — verified by enumerating `app.url_map` (53) against the PRD table row count (53). Coverage: logical clock setter; platforms (POST/GET×2/PATCH); estates (POST/GET×2, close, authority-resolution projection, grant-expiry-sweeps); fiduciaries; documents + transitions; authority-directives; digital-assets + transferability-reviews + subscription-terms; platform-requests + transitions; authority-grants + transitions; beneficiary-designations; disposition-elections + transitions; cancellation-orders + transitions + refund-claims; refund-claims + transitions; valuation-runs + transitions.

## Boot / behaviour confirmation

Booted via `bash start.sh` on self-chosen ports 41733 and 42911 (killed only by exact PID/port; ports confirmed free afterwards). Fresh boot answers `GET /platforms` with HTTP 200, `total_count: 0`, and the seeded logical clock at `2026-08-01T00:00:00.000Z`.

Two end-to-end smoke passes exercised: clock set → platform → estate → fiduciaries → death cert + letters VERIFY → ONLINE_TOOL/WILL directives → authority-resolution → assets → subscription term → platform request SUBMIT/START_REVIEW/DECIDE APPROVED → grant + disclosure cascade (`access_status` CONTENT_DISCLOSED, `disclosed_at` stamped) → auto-created PENDING cancellation order → REQUEST/CONFIRM (term CANCELLED, `auto_renew` forced false, billing state CANCELLED) → refund claim (`claimed_days` 184 closed-interval, PRORATA_DAILY `claimed_cents` 18400) → START_REVIEW/CREDIT (`refund_recovered_cents` 1000) → designations → valuation run → elections → finalize → close.

Verified spot-checks: the PRD's exact allocation example (3334/3333/3333 bp over 100 cents → 34/33/33 with `allocation_remainder_cents` 1 to rank 1); tiered `deduction_cap_cents` 25000 with `admin_deduction_cents` = request fee + pursuit costs; `ERR_STALE_ASSET_VERSION`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_ASSET_NOT_TRANSFERABLE` (SUBSCRIPTION licence rule), `ERR_BENEFICIARY_ALLOCATION_EXCEEDED`, `ERR_INVALID_ELECTION_STATE`, `ERR_VALUATION_NOT_FINALIZED` then successful close, `ERR_INVALID_RUN_STATE` on second finalize, `ERR_ESTATE_CLOSED` on a post-closure write, `ERR_MISSING_AUTH_HEADERS` (401), pagination meta (`limit`/`offset`/`total_count`/`has_more`), `limit=0` → `ERR_INVALID_REQUEST`, and unknown path → 404 in the error envelope.

Two PRD-vs-scaffold fidelity decisions made along the way: `finalization_note` is validated then discarded (ValuationRun declares no storage field for it), and the letters-revocation cascade hop 3 resets `content_clamp_reason` across **every** asset of the estate, not just the revoked grant's platform, per PRD §3.6.

## Step 5: Generate unit tests — 2026-09-04T16:52:00.000Z

Complete. Full verification passed.

## Delivered

Both directories are at the task root as siblings of `workspace/` — verified with `ls -la`; no stray `workspace/test_helpers` or `workspace/test_suite` exists.

**`test_helpers/`** — 2,318 lines / 9 files
`api_errors.py` 168 (all 68 error IDs + HTTP-status map, registered via `set_error_http_status_map`), `constants.py` 262, `test_users.py` 96, `api_client.py` 293 (one method per each of the 52 endpoints + singleton), `types.py` 285, `factories.py` 335, `assertions.py` 187 (incl. the three domain identity checkers), `fixtures.py` 616 (5-tier composite builders), `__init__.py` 72.

**`test_suite/`** — 9,790 lines / 18 files, **168 test functions → 201 collected cases**

| file | lines | tests | queue |
|---|---|---|---|
| conftest.py | 26 | — | — |
| test_01_dual_variant_calculations.py | 394 | 6 | A |
| test_02_combinatorial_formulas.py | 573 | 7 | A |
| test_03_non_linear_state_machines.py | 860 | 16 | A |
| test_04_transitive_cascades.py | 739 | 20 | A |
| test_05_validation_priority_conflicts.py | 366 | 8 | A |
| test_06_boundary_precision.py | 413 | 10 | A |
| test_07_cross_entity_state_dependency.py | 231 | 4 | A |
| test_08_resource_temporal_overlap.py | 225 | 5 | A |
| test_09_compensating_invariants.py | 535 | 8 | A |
| test_10_entity_lifecycle.py | 1336 | 35 | B |
| test_11_state_machine_corners.py | 1127 | 12 | B |
| test_12_calculation_corners.py | 803 | 7 | B |
| test_13_validation_corners.py | 577 | 4 | B |
| test_14_endpoint_corners.py | 366 | 6 | B |
| test_15_error_corners.py | 494 | 10 | B |
| test_16_rbac_corners.py | 294 | 5 | B |
| test_17_cross_cutting.py | 431 | 5 | B |

**Queue A: 84 tests. Queue B: 84 tests.**

## Coverage against the design indices

Indices parsed independently: 25 difficulty instances / 9 rule_ids; 48 corner instances / 9 sections, of which 7 are `excluded_because` stubs → 41 translatable.

- **24 of 25** difficulty instances translated, every one with ≥2 tests.
- **41 of 41** non-stub corner instances translated, every one with ≥1 test.
- **0** of the 7 stubs translated.

## Verification performed

- Every test carries **exactly one** `Design:` line; 0 untagged, 0 dual-tagged, 0 dangling, 0 tagging a stub — each tag string matched byte-for-byte against a `name:` field in the source yaml.
- All 168 docstrings contain a verbatim, whitespace-normalized PRD sentence (AST-driven substring check against `workspace/PRD.md`): 0 misses.
- `compileall` clean; all 17 modules import successfully (catches bad helper names); `pytest --collect-only` collects 201 cases with 0 errors.
- 0 occurrences of scaffold/design-file references, `mark.skip`, `mark.xfail`, `TODO`, or placeholders anywhere in the emitted code.

## Skipped

**1 instance skipped under the PRD-first filter:**
- `Difficulty/cross_entity_state_dependency/cancellation_request_depends_on_a_live_grant_on_another_aggregate` — the recipe asserts `ERR_NO_ACTIVE_AUTHORITY` on cancellation-order REQUEST, but PRD §3.7 states only the required `access_status` precondition and names no error ID there; the PRD binds `ERR_NO_ACTIVE_AUTHORITY` exclusively to disposition-election creation (§3.9). Outcome not uniquely derivable, so the whole instance was dropped rather than weakened.

**7 `excluded_because` stubs, not translated (by contract):** `state_machines/platform_request_approval_creates_the_grant_and_discloses_the_catalog`, `state_machines/estate_close_pins_the_phase_and_suppresses_further_derivation`, `calculations/allocation_floors_each_share_then_hands_out_the_remainder`, `rbac/delete_countersignature_cannot_be_supplied_by_the_electing_fiduciary`, `cross-cutting/the_asset_occ_token_guards_every_disposition_election`, `cross-cutting/approval_and_confirmation_cascades_reach_every_level`, `cross-cutting/both_valuation_bases_and_both_refund_methods_diverge_on_identical_data`.

## Design-index defects worth reporting upstream

Sub-assertions dropped because the recipe contradicts the PRD (the instance itself was still translated):
- `cancellation_confirm_cascades...` expects `open_cancellation_count == 1` after FAIL; PRD §2.10/§3.9 put it at 0.
- The counters corner instance asserts a three-term identity excluding `ELECTED`; PRD §2.10 counts `PENDING` **or** `ELECTED` and states a two-term identity.
- The consistency instance expects `subscription_billing_state == NOT_APPLICABLE` for a `SUBSCRIPTION` account; PRD §3.4 derives `ACTIVE`.
- The authority-projection instance asserts grant `basis == WILL_PROVISION`, not a member of the PRD's grant-basis enum.
- `every_path_parameter...` / asset-creation recipe expects `ERR_INVALID_REQUEST` for a client-supplied `transferability`; PRD §3.4 says such a value is ignored.
- `deduction_cap...` and several election recipes use field names (`reason`) that the PRD spells `denial_reason` / `reversal_reason`.

## Step 7: Run tests and iterate — 2026-09-04T17:14:24.000Z

Exactly the three intended files changed; `worklog.md` untouched.

## Summary

**Iterations run:** 2 (each an 8-round concurrent sweep). Iteration 1: 198/201 in all 8 rounds, with an identical 3-test union across every round — fully deterministic, no load-induced flakiness. Iteration 2: clean.

**Tests deleted:** none. All three failures traced to verbatim-PRD-covered rules; no test asserted a scaffold-only rule or a non-derivable outcome that couldn't be re-pointed at the PRD's own text.

**Fixes applied to `test_helpers/`:** none — the fixture/factory layer was sound.

**Fixes applied to `test_suite/`:**
- `test_suite/test_10_entity_lifecycle.py` — `test_malformed_asset_body_is_rejected_and_persists_nothing[missing_platform_id]`. The parametrized case fed `{"platform_id": None}` into `f.digital_asset_payload(platform["id"], **overrides)`, but `platform_id` is that factory's positional parameter, so Python raised `TypeError: got multiple values for argument 'platform_id'` before any request was issued. Replaced the splat with an explicit merge loop that reproduces the factory's own None-drops-the-key semantics, so the case can actually omit `platform_id` and exercise the PRD §2.7 band-1 required-field check. The other six parametrizations were unaffected and still pass.
- `test_suite/test_15_error_corners.py` — `test_a_delete_election_cannot_reach_submitted_without_a_countersignature`. STEP 2 assertion mis-translation. The test submitted a `DELETE` election sitting at `PENDING_COUNTERSIGN` and expected `ERR_COUNTERSIGN_REQUIRED`, but PRD §3.9 defines submission only as `DRAFT → SUBMITTED`, and §2.7 puts the entity-state band (6, `ERR_INVALID_ELECTION_STATE`) strictly above business safety (band 8, where `ERR_COUNTERSIGN_REQUIRED` lives). Re-pointed the assertion at `ERR_INVALID_ELECTION_STATE` and cited the §2.7 ladder sentence in the docstring. Notably, `test_03_non_linear_state_machines.py::test_submit_is_undefined_while_the_deletion_awaits_its_countersignature` already asserted the opposite code for the byte-identical scenario, quoting §2.7 verbatim — the two tests directly contradicted each other, and the ladder decides for `ERR_INVALID_ELECTION_STATE`. The implementation's `ERR_COUNTERSIGN_REQUIRED` guard is correct but unreachable in practice, since the only route to `DRAFT` for a `DELETE` is `COUNTERSIGN`, which necessarily sets `countersigned_by_fiduciary_id`. I left the guard in place rather than stripping a PRD-required check. All other assertions in the test (opens at `PENDING_COUNTERSIGN`, null countersigner, asset `version` +1, asset stays `PENDING`) were preserved — the version-bump assertion is unique to this test in the whole suite.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/valuation.py`, `execute_run` and `finalize_run` — `finalize_run` carried a comment claiming `finalization_note` had "no declared storage field on ValuationRun" and discarded the validated input. PRD §3.8 states verbatim that finalization "advances it to the terminal `FINALIZED`, stamps `finalized_at` and **stores an optional `finalization_note`**". Added `finalization_note: None` to the run record at creation and the assignment in `finalize_run`. `response.public()` has no field whitelist, so the field is now response-visible per §2.2's "operations that create or modify a resource will return the created or updated resource object".

**Final per-round figures:** rounds 1–8 all **201/201 passed**, 0 failed, 0 errors, empty failure union.

**Orchestrator independent verification:** re-read all 8 `results.$i.json` directly — every round reports `passed=201 total=201 failed=0 errors=0`. Artifacts present on disk (~64 KB each, all written 17:10). Sweep confirmed genuine, not a subagent claim.

## Step 8: Finalize PRD — 2026-09-04T17:17:30.000Z

Done. `PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Size delta
- PRD.md: 450 lines / 101,649 bytes. PRD_FINALIZED.md: 450 lines / 102,300 bytes.
- Line-count delta 0.0% (the PRD is one-paragraph-per-line); byte delta +651 (+0.64%). Three edits, all inline, no new sections.

## Changes
- §3.8 (run creation) — insert — a newly created run opens at `COMPUTED` with `finalized_at` **and** `finalization_note` present on the record and null — `implementation/services/valuation.py:83-85`.
- §3.8 (finalization) — insert — `finalization_note` is free text with no declared maximum length, is written onto the run and returned with it, and stays null when the caller supplies none — `implementation/services/valuation.py:151`, `implementation/routes/valuations.py:77,89`.
- §3.9 (submission) — insert — submission is defined only from `DRAFT`, so a `DELETE` election still at `PENDING_COUNTERSIGN` is refused with `ERR_INVALID_ELECTION_STATE` (§2.7 band 6) rather than the band-8 `ERR_COUNTERSIGN_REQUIRED`; the countersign guard is retained as the belt-to-the-braces statement — `implementation/routes/dispositions.py:227-238`.

**No edit for the `test_10` item.** `test_malformed_asset_body_is_rejected_and_persists_nothing[missing_platform_id]` was a pure fixture bug (positional-arg collision in the factory). Impl `routes/assets.py:30-38` declares `platform_id` as a required body field validated before any lookup, so an absent `platform_id` yields `ERR_INVALID_REQUEST` — already uniquely determined by §2.7 band 1 plus §3.4 ("names the `platform_id` of the provider hosting it"). PRD left verbatim.

## Per-edit pre-edit search log

**Edit 1 — run record fields at creation.**
(a) Subject: which fields exist on a `ValuationRun` at creation and their opening values, specifically `finalization_note`/`finalized_at`.
(b) Enumerated: `grep -rn 'DB.runs\|runs\b' implementation/` — the only run-record constructor anywhere is `services/valuation.py:73-87`; the only other writers are `finalize_run` (status/finalized_at/finalization_note) and `execute_run`'s supersede loop (status only, `valuation.py:68-71`). Readers: `services/lookup.py:66,146`, `services/estate.py:79-81,96-98,103,107`, `routes/valuations.py:22-90`. Field visibility: `response.public()` (`response.py:23-27`) strips only `_`-prefixed keys, so there is no whitelist that could hide the field on the create/read/list responses.
(c) Adjustment: wrote "present on the record and null" rather than "stored only at finalization", because the key is materialised at creation and therefore visible as `null` on `COMPUTED` and `SUPERSEDED` runs too (the supersede loop never touches it).

**Edit 2 — `finalization_note` validation and storage semantics.**
(a) Subject: the FINALIZE body field `finalization_note` — its type/length rules and what is stored when it is omitted or explicitly null.
(b) Enumerated: `routes/valuations.py:75-77` (`optional={"finalization_note": v_text()}`), `validation.py:28-30` (`v_text` = `v_str(max_len=None, allow_empty=True)`), `validation.py:109-130` (an explicit `null` on an optional field is treated exactly like an absent field, and unknown fields are rejected), `services/valuation.py:146-152` (`body.get(...)` → `None` on omission). Cross-checked the PRD's convention for the other free-text notes so the wording does not contradict them: `election_note`/`attestation`/`reason`/`rejection_reason`/`reversal_reason` (`routes/dispositions.py:191-197`), `inventory_note`/`review_note` (`routes/assets.py:37`) all use the same unbounded `v_text`.
(c) Adjustment: said "no declared maximum length" instead of "any string", and deliberately made no claim about non-emptiness, since `v_text` tolerates `""`; used "left null when the caller supplies none" so it covers both omission and an explicit `null`.

**Edit 3 — SUBMIT eligibility and its error code.**
(a) Subject: the error a disposition-election `SUBMIT` produces from a non-`DRAFT` state, and the reachability of `ERR_COUNTERSIGN_REQUIRED`.
(b) Enumerated every branch of `routes/dispositions.py:185-334`: SUBMIT (`status != "DRAFT"` → `ERR_INVALID_ELECTION_STATE` at :227, then the asset-`PENDING` check → same code at :229, then letters at :232, authority at :234, countersign at :236); COUNTERSIGN (`status != "PENDING_COUNTERSIGN"` → `ERR_INVALID_ELECTION_STATE`, and it always sets `countersigned_by_fiduciary_id`, :212-223 — so `DRAFT` is unreachable for a `DELETE` without a countersigner); REJECT/EXECUTE (`!= "SUBMITTED"`); REVERSE (`!= "EXECUTED"`, plus the asset-state check). Also checked the creation fork at :137 (`DELETE` → `PENDING_COUNTERSIGN`) and the guards that precede band 6 in the same handler (`require_fiduciary_estate`, `require_platform_scope`, `estate_svc.require_open`, :206-208), plus `authority.has_active_authority` (`services/authority.py:133-143`, which also requires the asset to be disclosed).
(c) Adjustment: scoped the sentence to submission-from-`PENDING_COUNTERSIGN` only and framed the countersign check as still normative ("belt to the braces") rather than deleting it, so the wording neither implies the guard is absent from the server nor makes any claim about bands 1-5, about COUNTERSIGN's own state check, or about the asset-`disposition_status` check that shares the same error code.

## Step 9: Complete PRD — 2026-09-04T17:38:00.000Z

Run as **three sequential, module-partitioned passes** over one shared `workspace/PRD_COMPLETED.md` (pass 1 owned the `cp`; passes 2 and 3 were explicitly forbidden to re-copy or whole-file-write). Partition of `implementation/`:
- **Pass 1** — app.py, response.py, db.py, clock.py, errors.py, validation.py, authz.py, money.py, routes/{system,common,platforms,estates,paperwork}.py, services/{estate,lookup}.py
- **Pass 2** — routes/assets.py, routes/requests.py, services/authority.py
- **Pass 3** — routes/{dispositions,refunds,valuations}.py, services/{valuation,refund}.py

### Pass 1 (infra + platforms/estates/paperwork) — 16 passages, 13 ambiguity-pins, 4 mismatch-revisions
- Ran `cp PRD_FINALIZED.md PRD_COMPLETED.md` (450 lines) → 451 lines / 107,819 chars (+5,519 chars).
- §2.1 — revise — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` count as absent for `ERR_MISSING_AUTH_HEADERS` — `authz.py:18`
- §2.1 — insert — ambiguity — an `X-User-ID` resolving to no `Fiduciary` row gets `ERR_FIDUCIARY_ESTATE_MISMATCH`, not an auth error — `authz.py:43-45`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase letters and digits — `response.py:13`
- §2.2 — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST`/404, bad method → 405, unparseable body or bad media type → 400, all in the error envelope — `app.py:46-64`
- §2.3 — insert — ambiguity — `created_at` ties broken by server creation order (never by `id`, never randomly), for both list pages and sibling cascades — `db.py:62-64`
- §2.3 — insert — ambiguity — filters are exact text matches (booleans as `true`/`false`); unmatched value → empty page; unrecognised query parameter ignored — `validation.py:155-170`
- §2.4 — insert — **mismatch** — the estate's derived pass (6 counters, `refund_recovered_cents`, `valuation_basis`, `administration_phase`) advances the estate's `version`/`updated_at` only when a recomputed value actually differs; the four money mirrors are not part of that pass — `services/estate.py:58-85`
- §2.5 — revise — ambiguity — `to_iso8601` required, any UTC offset normalised, truncated to whole milliseconds; response `data` is the single field `current_utc`; clock may move backwards — `clock.py:23-25`, `routes/system.py:16-18`
- §2.7 band 1 — revise — **mismatch** — body must be a JSON object (absent/whitespace body = empty object); explicit `null` == absence; **any** unknown field rejected; whitespace-only strings fail non-empty; an `action` outside the addressed entity's own action set is `ERR_INVALID_REQUEST` and only a defined-but-unowned action reaches `ERR_ACTION_ROLE_MISMATCH` — `validation.py:96-130`, `routes/paperwork.py:143`
- §3.1 — insert — ambiguity — every registration field except `status` is required, no other defaults — `routes/platforms.py:35-59`
- §3.1 — insert — ambiguity — an empty PATCH is accepted and still bumps `version`; body validated before `platform_id` resolves — `routes/platforms.py:87-94`
- §3.2 — revise — **mismatch** — verifying letters moves `letters_status` to `ISSUED` from any non-`ISSUED` value (including `REVOKED`), and the estate's `version` moves only per §2.4 — `routes/paperwork.py:160-165`
- §3.2 — revise — ambiguity — `revocation_reason` optional unbounded free text, null when omitted, accepted-and-ignored on `VERIFY` — `routes/paperwork.py:144,173`
- §3.2 — revise — **mismatch** — "every re-derivation advances the estate's `version`" narrowed to re-derivations that actually change the phase or a counter — `services/estate.py:83-84`
- §3.3 — revise — ambiguity — projection reads query-string params: `platform_id` required, `asset_category` must be a known category, both checked before the path estate resolves; estate resolves before platform; `asset_category` echoes null — `routes/estates.py:119-137`
- §3.6 (sweep only) — insert — ambiguity — a no-op sweep leaves the estate's `version` untouched; the sweep reads no request body — `routes/estates.py:140-184`
- §3.9 — revise — ambiguity — an estate with no valuation run at all fails the `ERR_VALUATION_NOT_FINALIZED` gate — `routes/estates.py:97-99`
- Pass 1 handoff note: it pinned the conditional estate bump in §2.4 and §3.2 rather than editing §2.10's cascade-closing sentence, to avoid colliding with passes 2/3.

### Pass 2 (assets / requests / authority) — 11 edits, 7 ambiguity-pins, 4 mismatch-revisions
- Did NOT re-copy. 451 lines before → 451 after; edits on lines 204–244, disjoint from pass 1's 17 edited lines.
- §3.4 — insert — ambiguity — `inventory_note` free text of no declared maximum length, null when omitted — `routes/assets.py:36,59`
- §3.4 — insert — ambiguity — `review_note` on a transferability review is accepted, validated, then recorded nowhere — `routes/assets.py:106-107`
- §3.4 — insert — ambiguity — the review bumps the account's `version` unconditionally even when the re-run reproduces the same class, and rewrites no estate counter — `routes/assets.py:114-118`
- §3.5 — insert — ambiguity — `requested_scope` is recorded but feeds nothing; the granted scope is the resolution's answer alone, so a `CATALOG_ONLY` ask can still be granted content — `routes/requests.py:74,265-271`
- §3.5 — insert — ambiguity — the `CONTENT_ACCESS` submission gate runs resolution with **no asset category**, so only `asset_category`-null directives are candidates — `routes/requests.py:156`
- §3.5 — insert — ambiguity — `decision` required with `DECIDE`, its absence `ERR_INVALID_REQUEST` raised before `ERR_ACTION_ROLE_MISMATCH`; the five payload fields otherwise optional, null when omitted, ignored on actions that don't name them; `DENIED` leaves `resolved_scope`/`resolved_basis` null and `clamp_reason` `NONE` — `routes/requests.py:176-187,256-261`
- §3.5 — insert — ambiguity — `RESUBMIT` does not re-apply the content-authority gate and does not clear `missing_items` — `routes/requests.py:227-240`
- §3.6 — revise — **mismatch** — grant `basis` enum corrected to the copied `resolved_basis` values (`ONLINE_TOOL`/`WILL_PROVISION`/`TRUST_PROVISION`/`STATUTORY_DEFAULT`, never `NONE`); every approval creates exactly one grant (even at scope `NONE`); decision-time resolution runs with no asset category — `services/authority.py:11-15,85,155`, `routes/requests.py:265,274`
- §3.6 — revise — **mismatch** — the disclosure hop's candidate set is `UNVERIFIED`/`ACCESS_REVOKED`/**`CATALOG_DISCLOSED`**; a `CATALOG_DISCLOSED` account is rewritten only when the new level is `CONTENT_DISCLOSED`, a `CONTENT_DISCLOSED` account is never visited, and a skipped account advances no `version` — `services/authority.py:173-190`
- §3.6 — revise — **mismatch** — a `granted_scope` of `NONE` skips the hop entirely (`ACCESS_REVOKED` accounts stay `ACCESS_REVOKED`) rather than "leaving the account at `UNVERIFIED`"; companion revise removed the now-false "only visits `UNVERIFIED` or `ACCESS_REVOKED`" justification and pinned that a skipped account gets no cancellation order — `services/authority.py:171-172`
- §3.6 — insert — ambiguity — auto-created `CancellationOrder` opens with `effective_date`/`platform_reference`/`failure_reason`/`requested_at`/`confirmed_at` null and `auto_renew_stopped` at `false`; "already has an order" means any status — `services/authority.py:200-213`
- §3.6 — revise — **mismatch** — registrar grant revocation accepts an optional `reason` and stores it nowhere (`revocation_reason` is the fixed `REGISTRAR_ORDER`); cascaded accounts keep `content_clamp_reason` and `disclosed_at` — only the letters cascade resets the clamp — `routes/requests.py:310,319`, `services/authority.py:220-240`
- **§3.3 needed no edit** — steps 0–4 of `resolve_authority` (candidate set, three sort keys with insertion-order tie-break, statutory default, court-order clamp, suspended-provider short circuit) already match `services/authority.py:43-100` uniquely.

### Pass 3 (dispositions / refunds / valuations) — 18 edits, 15 ambiguity-pins, 3 mismatch-revisions
- Did NOT re-copy or whole-file-write. 451 lines before → 451 after; bytes 111,904 → 116,907. Diff vs `PRD_FINALIZED.md` grew from 55 to 87 changed lines with none of passes 1–2's edits reverted.
- §2.8 — insert — ambiguity — `expected_estate_version`/`expected_asset_version` validated as non-negative integers, so a negative/non-integer is `ERR_INVALID_REQUEST`, not 412 — `routes/valuations.py:28`, `routes/dispositions.py:102`
- §3.4 — revise — **mismatch** — "keeps the appraisal until a fresh valuation run replaces it" was false; a run writes appraisals only onto included accounts — `services/valuation.py:92-99`
- §3.7 — revise — **mismatch** — the cancellation `REQUEST` guard is `has_active_authority` (ACTIVE grant for estate+platform **and** account disclosed) reported as `ERR_NO_ACTIVE_AUTHORITY`, not a bare `access_status` test; `effective_date` required on `REQUEST` — `routes/refunds.py:99-119`
- §3.7 — revise — **mismatch** — `FAIL` does not "change nothing else": the estate's counters are recomputed and a `FAILED` order leaves `open_cancellation_count` — `routes/refunds.py:154-158`
- §3.7 — insert — ambiguity — `CONFIRM` records `platform_reference` null and `auto_renew_stopped` `false` when omitted, forces the term to `CANCELLED` whatever state it held, and skips the hop when the account has no term — `routes/refunds.py:128-149`
- §3.7 — insert — ambiguity — order-transitions payload contract (5 optional fields, null-when-omitted, ignored on other actions, `failure_reason` falling back to generic `reason`) — `routes/refunds.py:90-96,155-156`
- §3.7 — insert — ambiguity — a new claim opens with `escalation_reason`/`denial_reason`/`chargeback_reason` present and null — `routes/refunds.py:222-226`
- §3.7 — insert — ambiguity — `credited_cents` required on `CREDIT` (`ERR_INVALID_REQUEST`) and capped at 100000000 — `routes/refunds.py:260,268-270`
- §3.7 — insert — ambiguity — claim-transitions payload contract incl. the three reason fields falling back to generic `reason` — `routes/refunds.py:257-265,294-328`
- §3.8 — insert — ambiguity — excluded accounts are not written at all: stale `appraised_value_cents`/`appraised_basis` retained, no `version` bump — `services/valuation.py:92-99`
- §3.8 — insert — ambiguity — every included account bumps `version` even when the appraisal is unchanged — `services/valuation.py:97-99`
- §3.8 — insert — ambiguity — the four estate money mirrors are rewritten unconditionally (always +1 to estate `version`), with the §2.4 derived pass adding at most one more — `services/valuation.py:118-122`
- §3.8 — insert — ambiguity — every designation bumps `version` on every run even when its planned allocation is unchanged — `services/valuation.py:139-140`
- §3.8 — insert — ambiguity — finalization writes nothing on the estate and leaves its `version`/`updated_at` alone — `services/valuation.py:146-154`
- §3.9 — insert — ambiguity — `election_note` unbounded free text stored null when omitted; `beneficiary_designation_id` resolved by id alone and not required to belong to the account's estate — `routes/dispositions.py:100-111,138`
- §3.9 — insert — ambiguity — countersign refuses non-`ISSUED` letters with `ERR_LETTERS_NOT_ISSUED` (before the segregation check), stores `attestation` null when omitted, and touches only the election — `routes/dispositions.py:212-224`
- §3.9 — insert — ambiguity — `SUBMIT` also requires the submitter's own `ISSUED` letters (`ERR_LETTERS_NOT_ISSUED`) and live authority (`ERR_NO_ACTIVE_AUTHORITY`), and an account not `PENDING` is refused with `ERR_INVALID_ELECTION_STATE` — `routes/dispositions.py:229-238`
- §3.9 — insert — ambiguity — `EXECUTE` error codes, `platform_confirmation_reference` null when omitted, authority deliberately not re-checked, plus the election-transitions payload contract — `routes/dispositions.py:189-197,259-286`
- §3.9 — insert — ambiguity — reversal leaves `platform_confirmation_reference` on the record — `routes/dispositions.py:316-318`

### Aggregate + orchestrator verification
- **Totals across the three passes: 45 edits — 35 ambiguity-pins, 11 mismatch-revisions** (one §3.6 revise counted once though it carried a companion sentence).
- `PRD.md` 450 lines / 101,649 chars → `PRD_FINALIZED.md` 450 / 102,300 → `PRD_COMPLETED.md` **451 lines / 116,907 chars** (+14,607 chars, +14.3%, over PRD_FINALIZED).
- Orchestrator re-verified independently: 27 headings present; `cmp PRD_FINALIZED.md PRD_COMPLETED.md` differs at byte 3030 (**not byte-identical — the scan genuinely ran**); 502 changed lines under a width-100 fold diff; file still ends on the real final error-table row `| ERR_OPEN_REFUND_CLAIMS | 409 |`, not mid-sentence.
- `find` over `workspace/implementation/`, `test_suite/`, `test_helpers/` for `*.py` newer than 17:12 returns nothing — Step 9 edited documentation only, so the Step 7 sweep result (8/8 rounds at 201/201) remains valid for the shipped artifact.

**PIPELINE COMPLETE.**
