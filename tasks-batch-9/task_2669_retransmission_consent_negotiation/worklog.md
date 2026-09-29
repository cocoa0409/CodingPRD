# Worklog — task_2669_retransmission_consent_negotiation

## Step 1: Create task directory — 2026-09-04T04:15:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2669_retransmission_consent_negotiation and its workspace/ subdirectory. Index 2669 was pre-assigned by the orchestrating caller; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-04T05:33:00.000Z

All three scaffold artifacts are complete and the linter is clean.

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_2669_retransmission_consent_negotiation/SCAFFOLD.yaml` — **2531 lines** (132 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2669_retransmission_consent_negotiation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — **1841 lines** (123 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2669_retransmission_consent_negotiation/SCAFFOLD_CORNER_DESIGN.yaml` — **3806 lines** (248 KB)

(directory also contains the pre-existing `worklog.md` and empty `workspace/` from the scaffold step)

## SCAFFOLD.yaml surface (§1.0–§1.7)
- Top-level keys: `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — contains **neither** `scaffold_difficulty_design` nor `scaffold_corner_design`.
- **14 entities**, **11 state machines / 46 transitions**, **2 concurrency rules** (OCC on `Negotiation` via `expected_negotiation_version`, on `CarriageAgreement` via `expected_agreement_version`), **6 calculations** (tiered_pricing, constraint_propagation, waterfall_allocation, threshold, interval_merge, chronological; 2 of them dual-variant), **39 ordered validations** (priorities 1-39, 401/403/400/404/409/422/412 bands), **48 endpoints**, **47 errors**, **6 roles** (`segregation_of_duties` role model with two entity-backed roles).

## Design instance counts
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: **18 instances** — all nine §0.5 difficulty rules with exactly 2 each (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- `SCAFFOLD_CORNER_DESIGN.yaml`: **79 instances** across all nine claim-guide sections — entities 12, state_machines 15, calculations 11, validations 21, endpoints 8, errors 2, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. Of these, **56 carry full `test_recipe`s** and **23 are `excluded_because` stubs** deferring to a named §1.8 instance.

## Verification
- 97 instance names across both design files, **zero duplicates**; **zero unbound `${var}`** references (every placeholder in a call path, payload, `as_user_id` or assertion is bound by an earlier `captures:` in the same instance); no stub carries a `test_recipe`; every one of the 47 error ids is referenced by at least one design instance.
- Two SCAFFOLD.yaml consistency repairs made during this pass: priority-3 pagination bound corrected from `limit in 1..200` to `limit in 1..100` (matching `pagination_defaults.max` and the error catalog), and a corner capture changed from the non-existent `CarriageAgreement.status` to `execution_status`.

Linter verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2669_retransmission_consent_negotiation/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2669_retransmission_consent_negotiation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2669_retransmission_consent_negotiation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  790

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

No sibling task directory was read, listed, globbed or grepped at any point.

## Step 3: Copy shared files — 2026-09-04T05:34:00.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes). Verified workspace/ intact after the Step 2 subagent.

## Step 4: Generate PRD — 2026-09-04T05:52:00.000Z

PRD complete and verified.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2669_retransmission_consent_negotiation/workspace/PRD.md`

- **Final line count: 471 lines** (96,956 bytes)
- **Exact text of the final heading: `## 5. Error Code Catalogue`** (line 421); the file ends on a real table boundary — last line `| \`ERR_EXTENSION_BUDGET_EXCEEDED\` | 422 |`

Built with 7 chunked `cat >> ... << 'EOF'` appends — no one-shot write, no truncation.

## Structure

`# Retransmission Consent Negotiation API — Product Requirements Document`
- **§1 Introduction** (3 paras, notes the `/retrans` mount)
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC; 2.2 API Response Structure (verbatim); 2.3 Pagination; 2.4 Identity/Timestamps/Revision Counters; 2.5 Logical Clock & Statutory Calendar; 2.6 Cents, Basis Points & Rounding; 2.7 Version Preconditions; 2.8 Path Resolution & Order of Rejection (numbered 1-39 precedence list); 2.9 Derived Counters & Cascades; 2.10 Ledger Visibility & Counterparty Confidentiality
- **§3 Business Logic** — 9 subsections (3.1 station/network obligations -> 3.9 settlement, split waterfall, expiration sweep)
- **§4 Endpoint Definitions** — 48-row, 4-column table
- **§5 Error Code Catalogue** — 47-row, 2-column table

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS**
- entity field names: 138 required, 0 missing
- endpoint input identifiers: 74 required, 0 missing
- output-shape identifiers: 11 required, 0 missing
- all 47 `errors[].id`, all 6 `roles[].name`, both `occ_field`s, all state values, all enum values present

**Contract 2 — Rule Coverage: PASS**
- validation `priority` ordering: §2.8 carries all 39 validations, contiguously numbered 1-39, each positionally matching its scaffold priority (item 4 references the 404 family declared in the same subsection), each with an explicit "Applies to ..." scope
- concurrency/OCC: both `expected_negotiation_version` -> `ERR_STALE_NEGOTIATION_VERSION` and `expected_agreement_version` -> `ERR_STALE_AGREEMENT_VERSION` at 412, stated in §2.7 and pinned at precedence 38-39
- cross-entity side effects: all cascades documented, including the 4-level `EXCLUDED` rights-dispute cascade (§3.8) and the substantiated-finding -> `true_up_required` flagging cascade (§3.4)
- all 46 state transitions covered (9 via explicit aggregated from-state lists)
- all 6 calculations rendered as prose with rounding order pinned; conservation invariant `gross = net + reverse_comp + rights_credit + penetration_penalty` stated
- sibling-branch symmetry stated for `RAISED`/`IN_MEDIATION` resolution paths, `NEGOTIATING`/`ELECTION_EFFECTIVE` withdrawal branches, and `MUST_CARRY`/`RETRANS_CONSENT`
- §4/§5 cross-checked mechanically: every scaffold method+path present with its exact role list; every error id present with its exact HTTP status (0 mismatches)

**Contract 3 — §3 Path Purity: PASS** — 836 backtick tokens scanned in §3; 0 leading-`/` tokens, 0 bare HTTP methods, 0 method+path combinations.

§2.2 verified byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`.

## Notes for the caller

Two places where the scaffold specifies a precondition but declares no error id; the generator named the least-ambiguous existing code rather than invent one:
1. The `file` transition's `requested_tier` in `permitted_tiers` check on the `RETRANS_CONSENT` branch (validation priority 28's `applies_to` names only the offers endpoint) — documented as `ERR_TIER_NOT_PERMITTED` in §3.3.
2. Turn-order violations on offer submission, which pass validation priority 10's state set but fail the transition precondition — documented as `ERR_NEGOTIATION_NOT_OPEN` in §3.5.

Constraints honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read.

**Orchestrator verification**: independently confirmed tail integrity — file ends with the complete 47-row error table at a real boundary, all 5 top-level sections and 25 subsections present. No truncation; no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T06:20:00.000Z

Implementation complete. Fresh boot yields an empty store (`total_count: 0`), confirming no seeding.

## Files written — `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 8 | foreground launcher, `exec python3 app.py`, guarded `pip install` (only when `import flask` fails) |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 68 | app factory, 5 blueprints, `ApiError`/`HTTPException`/catch-all handlers, global RLock per request, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 148 | constants (deadline, caps, credit bp), in-memory `DB` (14 empty dicts), logical clock, `base_row`/`touch` |
| `errors.py` | 110 | `ApiError` + all 47 catalogue codes -> HTTP status + message |
| `envelope.py` | 51 | `meta`/`response_type`/`data` envelope, `req_` id, 3-fraction-digit UTC, pagination meta |
| `common.py` | 180 | auth (`X-User-ID`/`X-User-Role`), field coercion, pagination (limit 1-100 default 10, offset >=0) |
| `calc.py` | 176 | ROUND_HALF_UP helpers, both fee ladders, subscriber basis, penetration penalty, split waterfall, midpoint/floor rules |
| `derive.py` | 478 | 404-family lookups, graph navigation, every derived counter, settlement recomputation, per-entity serializers |
| `routes_setup.py` | 280 | stations, affiliations, distributors, clock, 5-part expiration sweep |
| `routes_elections.py` | 232 | election CRUD, amend, file fork, withdraw cascade, negotiations list |
| `routes_reports.py` | 208 | reports, audit findings, finding resolution 3-level cascade, report-scoped settlements |
| `routes_negotiations.py` | 440 | offers (39-order gates), accept, reject, good-faith log, impasse, blackout notices |
| `routes_agreements.py` | 509 | agreements, network approval, execution + supersede cascade, fee projection, extensions, disputes (4-level cascade), settlements/true-up/void |

Total 2889 lines. **48 endpoints implemented** — exactly the PRD §4 table (46 domain routes + sweep + `/_clock/set_current_utc`).

## Smoke test (PORT=18669, then killed by its own PID; port confirmed free)

Two full scenarios plus edge probes, all passing:
- Canonical ladders verified: offer `year_rate_schedule_compound_cents = [250, 268, 287]`, agreement `contract_year_rate_schedule_cents = [250, 268, 285]`; projection `divergence_cents = 960000`.
- Conservation invariant `gross = net + reverse_comp + rights_credit + penetration_penalty` held at issuance, after an EXCLUDED-dispute re-price, and after true-up.
- Precedence/state checks fired correctly: `ERR_STALE_NEGOTIATION_VERSION` (412), `ERR_SEGREGATION_OF_DUTIES` on both execute and void, `ERR_NETWORK_APPROVAL_PENDING`, `ERR_NEGOTIATION_NOT_OPEN` (turn order), `ERR_GOOD_FAITH_NOT_SATISFIED`, `ERR_RATE_CAP_EXCEEDED`, `ERR_RIGHTS_NOT_GRANTABLE`, `ERR_DUPLICATE_ELECTION`, `ERR_ROLE_NOT_PERMITTED` (DistributorRep barred from the settlement ledger), `ERR_NEGOTIATION_NOT_FOUND`, pagination `limit=0`/`offset=-1` -> `ERR_INVALID_REQUEST`.
- Derived values checked: VMVPD notice deadline = expiry - 14d; 24 streaming devices -> basis 9; impasse -> `NOTICE_PENDING` -> `NOTICE_SERVED` -> station offer -> `NOT_REQUIRED` with notice `SUPERSEDED`; withdrawal cancelled the negotiation, expired all offers and returned `filed_election_count` to 0; sweep returned all five counts.

## Notable interpretation decisions
- Offers and execution require an `ACTIVE` affiliation unconditionally (PRD states no INDEPENDENT exemption there, unlike filing, which is explicitly exempted), so `network_approval_status = NOT_REQUIRED` is coded but unreachable in practice.
- No dedicated code exists for `call_sign`/distributor `name` uniqueness or `network_approval_status != PENDING_NETWORK`; these map to `ERR_INVALID_REQUEST` and `ERR_AGREEMENT_NOT_PENDING_EXECUTION` respectively.
- All counters are derived on read (never incremented), so compensating pairs are exact; every cascaded row still gets `updated_at`/`version` bumped.

## Step 5: Generate unit tests — 2026-09-04T06:31:00.000Z

Test suite generation is complete and verified.

## Output (all at the task root; nothing written into `workspace/`)

**test_helpers/ — 2057 lines, 9 files**
`__init__.py` 39 - `api_client.py` 255 - `api_errors.py` 108 - `assertions.py` 296 - `constants.py` 66 - `factories.py` 261 - `fixtures.py` 566 - `test_users.py` 57 - `types.py` 409

**test_suite/ — 4980 lines, 17 files**
`conftest.py` 46 - `test_01_dual_variant_calculations.py` 205 - `test_02_combinatorial_formulas.py` 170 - `test_03_non_linear_state_machines.py` 207 - `test_04_transitive_cascades.py` 156 - `test_05_priority_pair_conflicts.py` 149 - `test_06_boundary_precision.py` 160 - `test_07_cross_entity_state_dependency.py` 149 - `test_08_resource_temporal_overlap.py` 221 - `test_09_compensating_invariants.py` 138 - `test_10_corner_entities.py` 573 - `test_11_corner_state_machines.py` 517 - `test_12_corner_calculations.py` 212 - `test_13_corner_validations.py` 953 - `test_14_corner_endpoints.py` 498 - `test_15_corner_errors_and_rbac.py` 375 - `test_16_corner_concurrency_and_consistency.py` 251

## Totals

- **118 tests**, all collected by `pytest --collect-only` (0.54s); `pyflakes test_suite/*.py` clean; every file `ast.parse`-verified.
- **Queue A (§1.8): 18 of 18 non-stub instances translated, 0 skipped** — 38 tests across `test_01`-`test_09`.
- **Queue B (§1.9): 56 of 56 non-stub instances translated, 0 skipped** — 80 tests across `test_10`-`test_16`. Per section: entities 11, state_machines 11, calculations 4, validations 14, endpoints 7, errors 2, rbac 4, cross_cutting_complexity_layers 2, consistency_model 1.
- **No instance was skipped**, so there are no gap reasons to report.
- All **23 `excluded_because:` stubs** were verified (not translated): every `difficulty_instance` cross-reference resolves to a real §1.8 instance and every named `rule_id` matches the section that actually holds it. No stub was accidentally tagged by a test.

## Machine-verified compliance

A scripted pass over the AST confirmed: exactly one `Design:` line per test, always the final docstring line; 74 distinct tags (18 Difficulty + 56 Corner), each resolving to a real `name:` in the corresponding yaml; no untagged or dual-tagged tests; **147 PRD citations all byte-verbatim** against `workspace/PRD.md` after em-dash / arrow / bold-marker normalization; no occurrence of "scaffold", "design index", "§1.8", "§1.9" or `difficulty_instance` anywhere in the emitted code.

Three near-verbatim citations were repaired during this pass (backtick spans had been split) in `test_01`, `test_03` and `test_09`.

## Design-index vs PRD discrepancies resolved in favour of the PRD

1. `Corner/rbac/corner_peer_roles_cannot_reach_the_other_slots_rows` asked for `ERR_NOT_COUNTERPARTY` when a foreign distributor files a subscriber report. PRD §2.8 priority 6 enumerates eight operations and report filing is not one of them, and §3.4 takes `distributor_id` from the caller's own `X-User-ID`, so no ownership comparison can fail. Only the station-side half was translated.
2. `Corner/rbac/corner_other_roles_exclusive_operations_are_rejected` used a non-existent DistributorRep `X-User-ID`, which PRD §2.1 reports as `ERR_DISTRIBUTOR_NOT_FOUND`; a real distributor is registered for that one call so only the priority-2 role gate can fire.
3. `Corner/endpoints/corner_dismissed_finding_returns_report_to_reported` expects `ADJUSTED`, but PRD §3.4 uniquely derives `UNDER_AUDIT`; the PRD-derived state is asserted.
4. `Corner/entities` yaml carries an enum typo `INFORMATION_REQUESTED`; the PRD's `INFORMATION_REQUEST` was emitted. A non-derivable `version == 1` creation assertion was dropped, and a non-persistence check was re-expressed via global call-sign uniqueness.

**Orchestrator note**: Steps 5 and 6 were launched as two background agents in immediate succession rather than in a single message. The impl generator was additionally forbidden by prompt from reading `test_suite/`/`test_helpers/`, and its summary shows it never did; isolation held.

## Step 7: Test/fix iteration — 2026-09-04

Two parallel 8-round stability sweeps. Iteration 1: 97/118 in all 8 rounds, 21 failures, byte-identical across rounds (no flakiness). Iteration 2 after one implementation fix: **118/118 in all 8 rounds**.

### Root cause (single, upstream)

All 21 failures were the same timestamp-rendering defect in `workspace/implementation/store.py`. `fmt_dt()` unconditionally emitted three fractional digits (`2026-08-01T00:00:00.000Z`) for *every* instant in the system, including every domain `*_utc` business field.

PRD pins three fractional digits to exactly two fields — `api_request_timestamp` (§2.2) and `created_at` (§2.4). It pins nothing of the sort on the domain instants, and two verbatim sentences contradict the `.000Z` rendering:
- §2.5 "Before any client has set it, the logical clock reads exactly `2026-08-01T00:00:00Z`" — so every clock-stamped field (`filed_at_utc`, `impasse_declared_at_utc`, `served_at_utc`, `opened_at_utc`) and `current_utc` itself inherit second precision.
- §3.7 "carries the supplied `effective_start_utc` and `effective_end_utc`" — a client-supplied instant must round-trip, not be rewritten into the `created_at` house format.

### Fix — `store.py` only

- `fmt_dt()` now renders domain `*_utc` instants at the precision they actually carry: bare seconds when `microsecond == 0`, three digits otherwise so a sub-second input loses nothing.
- Added `fmt_dt_millis()` (always three digits) and pointed `base_row()`/`touch()` at it, so `created_at`/`updated_at` keep the precision §2.4 mandates.
- `envelope.py` formats `api_request_timestamp` independently and was untouched.

No test was deleted, weakened or skipped; no change to `test_suite/` or `test_helpers/`.

### Final sweep evidence

results.1-8.json: 118/118 passed, 0 failed, 0 errors in every round.

## Step 7: Run tests and iterate — 2026-09-04T06:45:00.000Z

Done — clean sweep reached.

## Summary

**Iterations run:** 2

**Tests deleted:** none. Every failing test survived STEP 1 (PRD verbatim-covers + uniquely derives) and STEP 2 (setup, request and assertion all faithful), so all 21 went to STEP 3 as implementation bugs.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`** — all in `workspace/implementation/store.py`:
- `fmt_dt()` — now renders domain `*_utc` instants at the precision they actually carry (bare seconds when `microsecond == 0`, three digits otherwise, so sub-second inputs lose nothing). Previously it forced `.000Z` onto every instant in the system.
- Added `fmt_dt_millis()` (always three digits) and repointed `base_row()` / `touch()` at it, so `created_at` / `updated_at` keep the precision PRD §2.4 mandates. `envelope.py` formats `api_request_timestamp` independently and needed no change.

**Key finding:** all 21 failures were one upstream defect, byte-identical across all 8 rounds of iteration 1 — no flakiness anywhere, so no load-induced noise to discount. The implementation applied the `created_at` house format (three fractional digits) to every business instant, which contradicts two verbatim PRD sentences:
- §2.5 "Before any client has set it, the logical clock reads exactly `2026-08-01T00:00:00Z`" — every clock-stamped field (`filed_at_utc`, `impasse_declared_at_utc`, `served_at_utc`, `opened_at_utc`) and `current_utc` inherit second precision from the clock.
- §3.7 "carries the supplied `effective_start_utc` and `effective_end_utc`" — a client-supplied instant must round-trip rather than be rewritten.

PRD pins three fractional digits to exactly two fields, `api_request_timestamp` (§2.2) and `created_at` (§2.4), and to nothing else — so the fix made the implementation *more* PRD-faithful rather than accommodating the tests. Worth noting that several failures tripped inside shared setup helpers before reaching their real assertions, so the format fix was load-bearing for far more than the formatting checks themselves.

**Final sweep evidence:** `results.1.json` ... `results.8.json` — **118/118 passed, 0 failed, 0 errors in all 8 rounds.**

**Orchestrator verification**: independently re-read all 8 results.$i.json — each reports passed=118, failed=0, errors=0, total=118. Files present and timestamped from the final sweep. Step 8 will run (Step 7 applied non-zero implementation fixes).

## Step 8: Finalize PRD — 2026-09-04T06:52:00.000Z

Done.

## Line counts
- `PRD.md`: 471 lines
- `PRD_FINALIZED.md`: 473 lines (+2 lines, **+0.42%**) — 1 revised sentence, 1 inserted paragraph. File still ends at the real close of §5 Error Code Catalogue.

## Changes
- **§2.4** — *revise* — `updated_at` now stated as carrying three fractional digits (PRD previously pinned three digits only to `created_at` and `api_request_timestamp`, leaving `updated_at` open) — `implementation/store.py:170-173` (`touch()` -> `fmt_dt_millis`), `store.py:162-167` (`base_row()`).
- **§2.4** — *insert* — new paragraph pinning the two-format split: fixed three-digit rendering is confined to `created_at`, `updated_at`, `api_request_timestamp`; every other instant-valued field (every `*_utc` field, plus `current_utc`) renders at the precision the instant actually carries — bare seconds on a whole second, three digits otherwise with sub-millisecond precision truncated — so client-supplied instants round-trip, clock-stamped fields inherit the clock's precision, and whole-day-derived instants inherit their source's precision — `implementation/store.py:110-127` (`fmt_dt`), `store.py:130-132` (`now_iso`).

## Per-edit pre-edit search log

**Edit 1 — `updated_at` precision**
- (a) Subject: the rendering precision of the `updated_at` bookkeeping field, and by extension every writer of it.
- (b) Paths enumerated: grepped `updated_at|created_at|fmt_dt|now_iso` across all of `implementation/`. Only two writers exist — `store.base_row()` (sets `updated_at = created_at`, both `fmt_dt_millis`) and `store.touch()` (`fmt_dt_millis`). Confirmed via `derive.py:287-474` that all 14 serializer key lists pass `created_at`/`updated_at` through verbatim with no re-formatting, and that `GOOD_FAITH_KEYS` (derive.py:365-368) omits `updated_at` entirely — so the existing §2.4 `GoodFaithLog` exception paragraph stays true. Every cascade-driven mutation (`routes_*.py`) reaches `updated_at` only through `touch()`.
- (c) No adjustment needed: both writers use the always-three-digit formatter unconditionally, so the universal claim is safe. Wording deliberately mirrors the existing `created_at` clause instead of introducing a competing formulation.

**Edit 2 — precision of domain `*_utc` instants and `current_utc`**
- (a) Subject: how every instant-valued output field other than `created_at`/`updated_at`/`api_request_timestamp` is rendered.
- (b) Paths enumerated: grepped every `_utc` occurrence in `implementation/` and confirmed the complete set of writers — `routes_setup.py:112` (`term_end_utc`), `:174` (`current_utc`); `routes_elections.py:82` (`incumbent_expiry_utc`), `:168` (`filed_at_utc`), `:181` (`blackout_notice_deadline_utc`), `:85`/`:180`/`:205` (explicit `None`); `routes_negotiations.py:270-271` (`effective_start_utc`/`effective_end_utc`), `:349` (`occurred_at_utc`), `:395` (`impasse_declared_at_utc`), `:422` (`served_at_utc`); `routes_agreements.py:247-248` (`extension_start_utc`/`extension_end_utc`), `:258` (agreement `effective_end_utc` rewritten by extension), `:420-421` (settlement period); `routes_reports.py:70-71` (report period), `:137` (`opened_at_utc`). Every one routes through `fmt_dt` or `now_iso` (which is `fmt_dt(clock)`); no `*_utc` field is ever stored as a raw client string or via `fmt_dt_millis`. Also checked `common.take_dt`/`store.parse_iso` (all comparisons re-parse stored strings, never string-compare), `envelope.py:15-20` (`api_request_timestamp` formats independently and remains fixed three digits — left untouched), `derive.py:423` and `calc.py:81,113` (consumers parse rather than compare text), and `routes_setup.py:188-272` (sweep parses stored strings). Ran the formatters directly to confirm the boundary cases: `us=0 -> ...:00Z`, `us=500 -> ...:00.000Z`, `us=123456 -> ...:00.123Z`.
- (c) Two wording adjustments made before committing. First, the whole-day-derived list was widened from `extension_end_utc`/`blackout_notice_deadline_utc` to also name the agreement `effective_end_utc` that `routes_agreements.py:258` rewrites, because an exhaustive two-item list would have wrongly excluded that off-Step-7 path. Second, "three fractional digits otherwise, any precision finer than a millisecond being truncated" was chosen over "when the instant carries milliseconds", so the us=500 case (which renders `.000Z`, not bare seconds) is described correctly rather than mis-stated as a whole second.

## Step 9: Complete PRD — 2026-09-04T07:15:00.000Z

Step 9 was deliberately run as **three sequential file-partitioned passes** over the same PRD_COMPLETED.md, rather than one subagent, so that the whole of `implementation/` (2889 lines across 14 files) actually got walked rather than sampled. Pass A did the `cp` from PRD_FINALIZED.md; passes B and C edited in place and were explicitly forbidden to re-copy or Write the whole file. Each pass handed unpinned findings in out-of-scope files forward to the next; Pass C reported explicit disposition for all 7 inherited hand-off items.

**Aggregate: 473 lines -> 473 lines (all edits in-paragraph, no new sections), 98,162 -> 114,203 chars (+16,041, +16.3%), 59 diff hunks vs PRD_FINALIZED.md. 49 ambiguity-pins + 10 mismatch-revisions = 59 changes.**

### Pass A — app.py, envelope.py, errors.py, common.py, store.py, routes_setup.py, routes_elections.py
21 ambiguity-pins, 5 mismatch-revisions. Highlights: whitespace-only auth header; `api_request_id` shape; `api_request_timestamp` taken from the host clock not the logical clock (mismatch); `has_more`/`total_count` semantics and pagination-meta omission on object responses; created_at tie-break by monotonic insertion sequence; inbound instant normalisation (Z / offset / naive / date-only); logical clock may be wound backwards; body validated wholly before id resolution; duplicate `call_sign`/distributor `name` -> `ERR_INVALID_REQUEST`; earliest-created `ACTIVE` affiliation governs; `EXPIRED` accepted at affiliation creation (mismatch); duplicate `permitted_tiers` collapse; station with no `ACTIVE` affiliation refused `ERR_TIER_NOT_PERMITTED` at filing; sweep lapse does not touch the station row and leaves `SERVED` notices `SERVED` (mismatch); re-filing after withdrawal creates an additional negotiation, so "exactly one negotiation" corrected (mismatch); five sweep phases run in listed order; trailing-slash/unrouted-path/405 behaviour (mismatch vs §5's 400).

### Pass B — routes_negotiations.py, routes_reports.py, calc.py
11 ambiguity-pins, 2 mismatch-revisions. Highlights: report creation resolves body `station_id` before header-derived distributor; a second finding on an already-`UNDER_AUDIT` report leaves the report row untouched; finding-status test precedes report-status test (noted as deliberately NOT propagated into §2.8 item 13, since impl checks finding first, contrary to the numbered order); dismissal leaves report untouched; literal list filters; `rejection_reason`/`impasse_statement` bounds; good-faith append leaves parent negotiation untouched though the counter moves; **impasse re-declaration from `IMPASSE` is accepted (mismatch)**; blackout-notice service is not gated on `IMPASSE` and leaves the negotiation untouched; **`notice_compliance_status` tests `SERVED` before `IMPASSE`, so `NOTICE_SERVED` wins over `NOT_REQUIRED` (mismatch, Pass A hand-off, verified)**; new agreement `decision_note` null; acceptance cascade does touch the station row. `calc.py` verified clean against the PRD on every formula, rounding mode and rounding order — no edit needed.

### Pass C — routes_agreements.py, derive.py
17 ambiguity-pins, 3 mismatch-revisions. Highlights: `ERR_RIGHTS_NOT_GRANTABLE` and `ERR_AFFILIATION_NOT_ACTIVE` also apply to network approval (2 mismatches in §2.8 items 25-26); **`decision_note` required non-empty and written on BOTH `APPROVE` and `REJECT` (mismatch)**; grantability subset test runs before the affiliation test so `ERR_AFFILIATION_NOT_ACTIVE` is reached only on an empty scope; `execution_note` validated then discarded, never persisted; SoD (priority 7) reported ahead of `PENDING_EXECUTION` (12); execution cascade visits candidates creation-ASC and moves an affected agreement's version exactly once; `current_year_rate_per_sub_cents` clamped into ladder bounds; `divergence_cents` recomputed from the accepted offer, not agreement term dates, five response keys; extension `effective_end_utc` moves forward by exactly `extension_days`; two `EXCLUDED` disputes on one term credit it twice; `MEDIATION` on an already-`IN_MEDIATION` dispute accepted; `period_label` uniqueness spans every status including `VOIDED`; settlement period need not lie inside the carriage term; **`contract_year_index` stored unclamped while `rate_per_sub_cents` reads a clamped index, so the two stored values can disagree**; `ACTIVE` and `EXPIRED` affiliations rank equally with earliest-created winning, no admissible affiliation -> premium and floor of zero; issuance never touches the distributor row.

Pass C's four "not-a-gap, unreachable" determinations (missing distributor/offer substitutions, empty-ladder rate-0 fallback, `current_year_rate_per_sub_cents` null case) were left unpinned on the grounds that no delete endpoint exists and `term_months >= 12` guarantees a non-empty ladder — correct calls; pinning unreachable branches would add PRD prose describing behaviour an implementer can never exhibit.

### Orchestrator verification
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (59 hunks, +16,041 chars) — the scan demonstrably ran.
- 27 headings intact; file ends at the real close of §5 Error Code Catalogue (`| \`ERR_EXTENSION_BUDGET_EXCEEDED\` | 422 |`). No truncation.
- No file under `implementation/` has an mtime newer than the green sweep's `results.1.json` (06:44:36) — Steps 8 and 9 were documentation-only, so the 8x 118/118 sweep evidence still holds for the shipped implementation.

**PIPELINE COMPLETE.**
