# Worklog — task_2374_solar_remove_reinstall_roof_replacement

## Step 1: Create task directory — 2026-09-02T04:48:15.000Z

Created `tasks/task_2374_solar_remove_reinstall_roof_replacement/` and `tasks/task_2374_solar_remove_reinstall_roof_replacement/workspace/`. Directory name was pre-allocated by the caller (no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T06:41:23.000Z

Scaffold complete and lint-clean at `/home/ubuntu/github/CodingPRD/tasks/task_2374_solar_remove_reinstall_roof_replacement/`.

**SCAFFOLD.yaml** (§1.0–§1.7) — `domain_name: solar-reroof-coordination`, `api_prefix: /reroof`, `difficulty_level: expert_plus` (harder than expert: `multi_party_negotiation` + `temporal_windowing`, four complexity layers, `parallel` state shape, `segregation_of_duties` role model):
- 12 entities (ReroofProject, Party, Jurisdiction, PartyApproval, ArrayCircuit, HardwareUnit, StorageBin, DeckFinding, PermitApplication, Inspection, WorkWindow, SourcingOrder)
- 9 state machines (HardwareUnit carries two independent dimensions; PartyApproval/PermitApplication cyclic; ReroofProject compound with an authorization-withdrawal cycle)
- 2 §1.2.1 OCC rules (both `expected_project_version` → ERR_STALE_PROJECT_VERSION/412)
- 10 calculations (two dual-variant: downtime credit provisional-vs-final, warranty strict-vs-lenient; plus tiered deck-upgrade cost, permit fee, crew-window overlap, inspection slots, watt spread, match classification, posture, bin occupancy)
- 31 priority-ordered validations, 55 endpoints, 44 errors, 6 roles
- Test-driving hooks: `POST /reroof/_clock/set_current_utc`, `POST /reroof/_ledger/perturb`

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8) — 9 rules / 21 instances (dual-variant, combinatorial formula, non-linear state machine, transitive cascade, priority-pair conflict, boundary precision, cross-entity state dependency, resource/temporal overlap, compensating invariant).

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9) — all nine taxonomy sections, 67 instances: entities 10, state_machines 15, calculations 14, validations 9, endpoints 5, errors 5, rbac 3, cross_cutting_complexity_layers 5, consistency_model 1. 51 carry a full `test_recipe`; 16 are `excluded_because` stubs, each citing an existing §1.8 instance by name.

Verification performed: `scaffold_lint.py` → `VERDICT: clean lint` (1085 calls scanned); all 44 error ids are triggerable across §1.8+§1.9; both concurrency rules have an OCC stale-version test using their declared `write_endpoint`/`occ_field`; instance names unique across both design files; no instance has both `test_recipe` and `excluded_because`; every `${var}` resolves to a capture in its own instance. Two self-caught assert bugs were fixed (a `warranty_variant` pinned at removal, and `round_recorded` on the approval that itself requested changes — the round-bump cascade re-bases only APPROVED rows). One design smell was left as-is deliberately: `DECK_WORK -> REINSTALL` is only evaluated from the deck-finding-upgrade and permit-decision endpoints, so every lifecycle chain routes through a waived LOW finding, matching §1.8's canonical path.

## Step 3: Copy shared files — 2026-09-02T06:41:23.000Z

Copied `INSTRUCTION.md` → `tasks/task_2374_solar_remove_reinstall_roof_replacement/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T06:54:10.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2374_solar_remove_reinstall_roof_replacement/workspace/PRD.md` — **456 lines, ~11,700 words**.

**Sections covered**

- **§1 Introduction** — the three-party coordination triangle, the remove-and-reinstall lifecycle, and the two framing commitments (derived safety posture; conserved credit ledger).
- **§2 Global Specifications** (11 subsections): 2.1 identity/RBAC with all 6 roles and per-role `X-User-ID` semantics (opaque coordinator, `Party`-backed contractors/owners, `Jurisdiction`-backed inspector) plus the four concrete ownership comparisons; 2.2 response envelope pasted verbatim from the skill asset; 2.3 pagination; 2.4 record identity, timestamps, `Jurisdiction`'s no-`updated_at`/no-`version` exception, and the logical clock defaulting to `2026-08-01T00:00:00Z`; 2.5 left-to-right path resolution, body-FK 404s, and the three cross-project refusal sites; 2.6 posture as a two-tier gate (FROZEN bar on 6 operations, OPEN-only bar on reinstall and re-energize); 2.7 the four credit accounts and their conservation identity; 2.8 rounding discipline; 2.9 OCC on the two `expected_project_version` writers; 2.10 cascade/roll-up semantics and the two population identities; 2.11 the full 31-step validation precedence with four worked precedence consequences.
- **§3 Business Logic** (9 workflow subsections): reference data → project + consent negotiation (round cascade, `SYSTEM_OWNER` veto from AUTHORIZED vs DEENERGIZED) → crew windows and symmetric mobilization buffer → de-energization interlock fork → removal/storage/dual-dimension grading → deck findings, 4-step tiered upgrade pricing with the floor-beats-cap nest, and the 4-level re-permit cascade → permit fee terms and AHJ inspections (backlog floor then jurisdiction-wide day capacity; CORRECTION keeps the slot) → 5-step sourcing classification with pre-mutation snapshot tolerance → reinstall, the two opposed warranty variants, commissioning, and both credit variants (single terminal rounding vs per-day rounding before summing).
- **§4** 55 endpoint rows (Method / Path / Description / Authorized Role(s)) — matches the scaffold exactly, no extras, no omissions.
- **§5** all 44 error IDs with statuses, including `ERR_UPGRADE_BUDGET_EXCEEDED` at 402 and `ERR_STALE_PROJECT_VERSION` at 412.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 136 required, 136 present, 0 missing
- endpoints[].request_body: 102 required, 102 present, 0 missing
- endpoints[].query_params: included in the 102 above, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_project_version + ERR_STALE_PROJECT_VERSION all named), 0 missing
- state_machines[].transitions: 53 checked, 53 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 55 checked, 55 expressed, 0 missing
- entities[].fields[] structured content: 11 entities checked, 11 reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups checked (SCOPE/COMPLETE/WAIVE/RESCOPE, APPROVE/REQUEST_CHANGES, DE_ENERGIZE interlock true/false, START/COMPLETE/WEATHER_ABORT, PASS/FAIL/CORRECTION, permit APPROVE/REJECT, strict/lenient warranty variants), 7 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 877
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Audit findings and repairs (2 passes):** first pass surfaced one missing identifier, `permit_application_id`, now placed in §3.7 as the inspection's only route to a project; and two fidelity drifts against endpoint `side_effects` — the `REINSTALL → COMMISSIONED` bubble from an inspection pass is narrowed to `ELECTRICAL_FINAL` (§3.7 and §3.9), and the `PASS` precondition that the parent application still be `SUBMITTED` or `APPROVED` was added. Second pass clean on all three contracts. Note the scaffold defines 44 errors (not 45); the catalogue matches one-for-one with zero extras. The withheld design files were never opened, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T07:51:37.000Z

Orchestrator note: Steps 5 and 6 were launched in **separate** messages rather than concurrently, so `test_suite/` existed on disk when Step 6 started. The skill's physical-isolation guarantee was therefore replaced by an explicit absolute prohibition in Step 6's prompt (no read/list/glob/grep of `test_helpers/` or `test_suite/`).

Done. Test infrastructure and suite are generated, audited, and clean.

## Files written

`test_helpers/` (Stage 1, 9 files): `__init__.py` (barrel re-exporting the framework generics + all local modules), `types.py` (24 status enums + entity TypedDicts; `Jurisdiction` deliberately carries only `id`/`created_at`), `api_client.py` (`ApiClient` with one method per PRD §4 endpoint, prefix `/reroof`, incl. `_clock/set_current_utc` and `_ledger/perturb`), `api_errors.py` (45 error ids + HTTP map registered with the validator), `constants.py` (published rates/tiers/thresholds), `factories.py` (input-only payload builders), `test_users.py` (`TEST_USERS` + per-entity `make_*_headers` builders), `assertions.py` (per-entity shape checks + `assert_credit_ledger_identity`, `assert_unit_population_identity`, `assert_bin_occupancy`), `fixtures.py` (granular action helpers + phase composites `setup_authorized_project` → `setup_deenergized_project` → `setup_deck_work_project` → `setup_reinstall_project` → `setup_commissioned_project`).

`test_suite/` (Stage 2): `conftest.py` + 16 test files, **101 test functions / 107 collected items**.

| Queue | Files | Tests |
|---|---|---|
| A (Difficulty) | `test_01`…`test_09` | 49 |
| B (Corner) | `test_10`…`test_16` | 52 |

## Coverage

- **Queue A: 21/21 difficulty instances translated, all with ≥2 tests** (2–4 each). No skips.
- **Queue B: 51/51 non-stub corner instances translated, all with ≥1 test.** No skips. All 16 `excluded_because:` stubs correctly left untranslated; I verified all 16 `difficulty_instance:` cross-references resolve to real names in the difficulty index (0 broken pointers).

## Audit results (all passing)

- Every test has **exactly one** `Design:` line; every tag's rule_id/section and instance name match the source yaml verbatim; **zero** dangling, dual-tagged, untagged, or stub-derived tests.
- Every one of the 101 docstrings contains a machine-verified verbatim sentence from `workspace/PRD.md`.
- No docstring or comment mentions "scaffold" or any scaffold section/table reference.
- `pytest --collect-only` on the whole suite: 107 collected, 0 errors. `pyflakes` clean on all test files and all helper modules.
- No test uses the shared `TEST_USERS` constants — identity is threaded from real `Party.id`/`Jurisdiction.id` everywhere.

## Judgement calls worth surfacing

1. **One assertion removed by me** in `test_09_conservation_invariants.py`: the design index asserts a scrapped unit retains `storage_bin_id`/`storage_label`. The PRD states that retention only for the *reinstall* path (§3.9 "deliberately retained as provenance") and is silent for scrap, so it is not uniquely derivable. The instance's actual claims (slot freed, population conserved) remain asserted.
2. **A yaml/PRD contradiction** in corner instance `corner_pending_approval_left_behind_by_a_round_bump_is_stale`: the index expects the objecting record's `round_recorded == 1`, but PRD §3.2 says the objector's own `round_recorded` *is* re-based to the new round. That single assertion was omitted; the instance's `ERR_APPROVAL_ROUND_STALE` core (the stranded sibling) is tested.
3. Minor recipe deviations, all preserving the asserted outcome: dropped a `?status=` circuit-list filter the PRD's endpoint table does not document; re-threaded one RBAC window scenario whose recipe identity would have produced `ERR_PARTY_NOT_ON_PROJECT` instead of the intended assertion; asserted the PRD's error `meta`/`data` envelope shape rather than the recipe's `data == null`.

## Step 6: Generate implementation — 2026-09-02T07:51:37.000Z

Implementation is complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2374_solar_remove_reinstall_roof_replacement/workspace/implementation/`:

- `start.sh` (executable) — `cd`s to its own dir, guarded `pip install` (only when `import flask` fails), `exec python3 app.py`, honours `PORT` (default 10000), binds `0.0.0.0`.
- `app.py` — blueprint registration + `ApiError` / `HTTPException` / catch-all handlers, all in the envelope format.
- `db.py` — in-memory dicts only; store starts empty, nothing seeded. Logical clock defaults to `2026-08-01T00:00:00Z`, never falls back to wall clock.
- `errors.py` (all 45 error IDs), `response.py` (envelope, `req_` id, 3-fractional-digit UTC), `validation.py` (schema step + pagination), `middleware.py` (auth/role), `calc.py` (11 pinned calculations), `services.py` (posture, roll-ups, phase machine, cascades).
- `routes/`: `helpers.py`, `reference.py`, `projects.py`, `field.py`, `deck.py`, `permits.py`, `windows.py`, `sourcing.py`, `admin.py`.

**55 API endpoints** registered, matching the PRD §4 table exactly (56 rules including Flask's `/static`).

## Verification
Three smoke suites (via test client) all pass, plus a real `bash start.sh` boot + curl check. Covered: full LEASE lifecycle INTAKE→CLOSED, HOST_OWNED and PPA variants, SYSTEM_OWNER veto round cascade, ISOLATION_PENDING fork, bin capacity/type/label rules, deck-cost tiers (267950, 66500, frozen-bump floor 50000), depth-4 re-permit cascade (permit `APPROVED→SUBMITTED`, `revision_count`, fee 76270, `PASSED→CORRECTION_REQUIRED` with `attempt_number` 2), permit fees with expedite + revision surcharges, inspection backlog floor and per-jurisdiction slot capacity, mobilization-buffer adjacency conflict, weather-abort→RESTRICTED, reschedule/supersede, match classification with tolerance bonuses, watt-spread boundary (3.00 accepted / above refused), warranty variants (10 vs 25 risk points), provisional credit (1680, 1585) vs per-day final credit (6160), and the ledger-perturb → `ERR_CREDIT_LEDGER_UNBALANCED` guard.

## PRD ambiguities resolved (judgment calls)
1. **Project `version`**: bumped **at most once per request**, driven by a snapshot diff over 26 tracked project fields; forced on `warranty-notice`, `sourcing-orders` create and `_ledger/perturb` (which the PRD says increment explicitly even when nothing else changes).
2. **All timestamps use the logical clock**, including `api_request_timestamp`; an insertion `_seq` breaks `created_at ASC` ties.
3. **Duplicate jurisdiction `code`** has no dedicated error → `ERR_INVALID_REQUEST` (422).
4. **Conditionally required body fields** (`waiver_reason` on WAIVE, `abort_reason` on WEATHER_ABORT, `rejection_reason` on REJECT) validated at precedence step 5 → `ERR_INVALID_REQUEST`.
5. **`interlock_verified` required on both** DE_ENERGIZE and RE_ENERGIZE.
6. **Undeclared transitions → `ERR_INVALID_STATE`**: DE_ENERGIZE with `interlock_verified=false` from `ISOLATION_PENDING`; `SERVICEABLE` grade with `SCRAP` disposition; re-grading `SERVICEABLE→SERVICEABLE` or `DAMAGED→DAMAGED/RETAIN`; scrapping a `REPLACED` unit. `DAMAGED+SCRAP` **is** allowed from a `DAMAGED` condition (only the handling dimension moves).
7. **`ISOLATION_PENDING→ISOLATED`** does not re-require `phase == AUTHORIZED` (PRD restates the phase precondition only for the `ENERGIZED` origin).
8. **PASS on an inspection whose parent permit is no longer SUBMITTED/APPROVED** → `ERR_PERMIT_NOT_SUBMITTED` (same predicate the PRD names with that error), not `ERR_INVALID_STATE`.
9. **Approval decision order** inside step 8: transition legality first, then `ERR_APPROVAL_ROUND_STALE` (reachable via a sibling left `PENDING` when the round advances — only `APPROVED`/`CHANGES_REQUESTED` siblings get refreshed).
10. **`CHANGES_REQUESTED` sibling reset** clears `veto_flag` but not `decided_at`; an `APPROVED` sibling reset clears `decided_at` (literal PRD reading).
11. **Party-type suitability not applied** to deck-finding *creation* (only the four upgrade actions) nor to `work-windows/{id}/reschedule`; reschedule inherits `trade`/`project_id` and copies `weather_risk_score` when omitted.
12. **Ownership on `work-windows/{id}/status`** enforced only for entity-backed roles, never for the opaque `ProjectCoordinator`.
13. **`reinspection_gate_satisfied`**: no permits ⇒ satisfied; no permit's jurisdiction requires reinspection ⇒ satisfied; else a `PASSED ELECTRICAL_FINAL` under an `APPROVED` permit is required.
14. **Receipt duplicate-serial check excludes the target unit** itself (its serial is overwritten by the same write).
15. **Query-string enum filters are validated** against their enum → `ERR_INVALID_REQUEST`.
16. Extra convenience fields persisted where the PRD implies recording but never lists them: `isolation_note`, `disposition`, `settlement_note`, `decision_note`, `review_note`.


## Step 7 (resume assessment) — 2026-09-02T12:05:00.000Z

Orchestrator resumed after a crash. Verified on disk: `SCAFFOLD.yaml` (2718 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2219), `SCAFFOLD_CORNER_DESIGN.yaml` (4145), `workspace/INSTRUCTION.md` (53), `workspace/PRD.md` (455), `test_helpers/` (9 files, 2113 lines), `test_suite/` (conftest + 16 files, 7132 lines), `workspace/implementation/` (18 py files + start.sh, 3819 lines). All parse-complete and non-truncated — Steps 1–6 accepted as valid, not regenerated.

Step 7 was in flight when the run died: no `results.*.json` survived (the last gated attempt `rm`'d them before launching). Salvaged `.sweeplogs/` shows partial rounds killed mid-sweep, with load-induced `ERROR` entries on tests that `PASSED` in a sibling round (e.g. `test_02::test_attachment_floor_out_ranks_the_cap`, `test_10::test_project_listing_is_paginated_and_filterable_by_phase`). Host load at resume: 299 (32 cores), 494 concurrent `prd-bench-local-run` processes from sibling pipelines. Step 7 relaunched from scratch as a fresh long-lived subagent.


## Step 7: Run tests and iterate — 2026-09-02T13:12:40.000Z

Clean 8-round parallel sweep achieved on the first iteration.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep).

**Sweep result:** all 8 rounds `107 / 107` passed (`passed == total` in every `results.${i}.json`, i = 1..8), with the `sweep.done` marker present. Sweep was run under `setsid nohup` with `--isolation per-test-server`, on a heavily contended host (487 concurrent `prd-bench-local-run` processes from sibling pipelines, load ~200); wall time ~25 min. Zero failures, zero errors, zero flakiness — so the diagnostic protocol (STEP 0–3) never had a failing test to operate on.

**Tests deleted:** none — no test failed in any round, so no PRD-coverage or unique-derivability adjudication was triggered.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:** none needed.

**Verification / hygiene:**
- Confirmed `workspace/implementation/` storage is in-memory only: `db.py` holds process-local dicts, `Store.reset()` starts every collection empty, logical clock defaults to `2026-08-01T00:00:00Z`, and a grep for `sqlite|open(|json.dump|/tmp|pickle|shelve` across all implementation `.py` files returns nothing — no disk persistence and no seeded entity data.
- Removed the stale artifacts left by the crashed prior run so downstream steps cannot mistake them for current evidence: `.sweep.sh`, `.gsweep.sh`, `.pgsweep.sh`, `.gated_sweep.sh`, `.sweeploop.sh`, `.verify_isolated.sh`, `.sweeplogs/`, plus this sweep's `workspace/sweep.log` / `sweep.done` markers. The 8 `workspace/implementation/results.${i}.json` files from the clean sweep are retained as evidence.

Task dir now contains only `SCAFFOLD*.yaml`, `test_helpers/`, `test_suite/`, `worklog.md`, `workspace/`.

**Orchestrator independent verification:** re-read all 8 `results.${i}.json` directly — every round reports `passed=107 total=107 failed=0 errors=0`. Step 7 accepted as complete.


## Step 8: Finalize PRD — SKIPPED — 2026-09-02T13:13:05.000Z

Skip condition met per the skill: Step 7 exited on its first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the test suite exercised, and there is no `<step_7_diff>` to target. No subagent spawned; `workspace/PRD_FINALIZED.md` is intentionally absent. Step 9 will start from `workspace/PRD.md`.


## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T13:22:30.000Z

Done. `PRD_COMPLETED.md` is written.

## Counts

- **Source**: `workspace/PRD.md` — 455 lines, 85,039 chars
- **Output**: `workspace/PRD_COMPLETED.md` — 455 lines, 96,305 chars (**Δ +11,208 chars**)
- 40 lines changed, all 1-for-1 in-paragraph replacements — no new sections, no new paragraphs, no line-count change
- **Ambiguity-pins: 34** · **Mismatch-revisions: 6**

## Changes

- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — `response.py:36`
- §2.3 — revise — ambiguity — unparseable `limit`/negative-or-unparseable `offset` → `ERR_INVALID_REQUEST`; empty string = absent — `validation.py:147`
- §2.3 — revise — ambiguity — `created_at` ties broken by server insertion order (logical clock collides) — `db.py:68`
- §2.3 — revise — ambiguity — `has_more` = `offset + returned rows < total_count`; `total_count` is pre-paging — `response.py:72`
- §2.4 — revise — ambiguity — clock endpoint returns a `data` object with the single `current_utc`; accepts any parseable instant including a backwards one — `admin.py:16`
- §2.7 — revise — ambiguity — `released_delta_cents` may be negative; perturb answers with the project; summary also carries `project_id` — `admin.py:29`, `projects.py:211`
- §2.10 — revise — **mismatch** — project `version`/`updated_at` advance only when a tracked project field's *value* changes; four writes force it; bins touched only on occupancy change — `services.py:105`, `services.py:6`, `services.py:163`
- §2.11 (5) — revise — ambiguity — non-object body / absent body / JSON `null` / non-empty strings / bool-rejecting ints / ignored extra fields / enum query filters — `validation.py:15`
- §2.11 (8) — revise — ambiguity — transition legality precedes round-freshness on a consent decision — `projects.py:384`
- §3.1 — revise — ambiguity — malformed **or duplicate** jurisdiction `code` → `ERR_INVALID_REQUEST` — `reference.py:92`
- §3.2 — revise — ambiguity — project's `warranty_notice_filed_at`, `warranty_notice_reference`, `settlement_note` start absent; `weather_abort_count`/credit figures zero — `projects.py:146`
- §3.2 — revise — ambiguity — new consent record's `decision_note` starts absent — `projects.py:330`
- §3.2 — revise — ambiguity — `decision_note` written only when supplied — `projects.py:402`
- §3.2 — revise — **mismatch** — a sibling already `PENDING` is left untouched and goes stale; `CHANGES_REQUESTED` branch keeps `decided_at` — `projects.py:422`
- §3.2 — revise — ambiguity — a non-`SYSTEM_OWNER` change request past consent leaves `phase` alone — `projects.py:438`
- §3.3 — revise — ambiguity — new window's `abort_reason` starts absent — `windows.py:112`
- §3.3 — revise — ambiguity — illegal window action → `ERR_INVALID_STATE`; early `START` → `ERR_INVALID_STATE` before frozen bar; `weather_risk_score` written on all three actions; only `START` is posture-gated — `windows.py:177`
- §3.3 — revise — ambiguity — missing `abort_reason` → `ERR_INVALID_REQUEST` — `windows.py:164`
- §3.3 — revise — **mismatch** — reschedule is **not** posture-gated and does **not** re-check party type; inherits `trade`/`party_id`/`weather_risk_score`; response is the new row — `windows.py:217`
- §3.4 — revise — ambiguity — circuit's `isolation_note` starts absent and is written only when supplied; `interlock_verified` required on both actions — `field.py:78`, `field.py:107`
- §3.4 — revise — ambiguity — wrong phase / already-`ISOLATED` / `ISOLATION_PENDING`-with-false-interlock → `ERR_INVALID_STATE`; phase **not** re-checked on the second leg — `field.py:114`
- §3.5 — revise — ambiguity — unit carries `disposition`, `damage_note`, `storage_position`, all absent at registration; registration ungated — `field.py:280`
- §3.5 — revise — ambiguity — non-`ON_ROOF` removal → `ERR_INVALID_STATE`; removal takes no body — `field.py:340`
- §3.5 — revise — ambiguity — `storage_position` ≥ 1, no uniqueness within a bin; non-`REMOVED` → `ERR_INVALID_STATE` — `field.py:376`
- §3.5 — revise — **mismatch** — grading: `SERVICEABLE` requires `RETAIN` and only from `UNINSPECTED`; `DAMAGED`+`RETAIN` only from `UNINSPECTED`/`SERVICEABLE`; `SCRAP` from any but `REPLACED`; all `ERR_INVALID_STATE`; `damage_note` written only when supplied — `field.py:441`
- §3.6 — revise — ambiguity — missing `waiver_reason` on `WAIVE` → `ERR_INVALID_REQUEST`; illegal action per branch → `ERR_INVALID_STATE`; unresolvable actor party → `ERR_PARTY_TYPE_MISMATCH` — `deck.py:153`, `helpers.py:139`
- §3.6 — revise — **mismatch** — the re-permit cascade reopens **every** qualifying `APPROVED` permit, in `created_at` order — `deck.py:116`
- §3.7 — revise — ambiguity — submission from `SUBMITTED`/`APPROVED` → `ERR_INVALID_STATE`; no body, ungated — `permits.py:144`
- §3.7 — revise — ambiguity — deciding a non-`SUBMITTED` permit → `ERR_INVALID_STATE`; missing `rejection_reason` → `ERR_INVALID_REQUEST` — `permits.py:178`
- §3.7 — revise — ambiguity — result from non-`SCHEDULED` → `ERR_INVALID_STATE`; `PASS` with a departed parent → `ERR_PERMIT_NOT_SUBMITTED`; `result_note` only when supplied — `permits.py:324`
- §3.8 — revise — ambiguity — order state violations → `ERR_INVALID_STATE` (condition before handling); `review_note`/`received_*` start absent; percentages are JSON numbers — `sourcing.py:56`, `sourcing.py:106`
- §3.8 — revise — ambiguity — reviewing a non-`PENDING_REVIEW` order → `ERR_INVALID_STATE`; `review_note` only when supplied; review does not bump the project — `sourcing.py:170`
- §3.8 — revise — ambiguity — receipt of a non-`APPROVED` order → `ERR_INVALID_STATE`; the target unit is excluded from the serial-uniqueness scan — `sourcing.py:192`, `sourcing.py:216`
- §3.8 — revise — ambiguity — receipt's response body is the order, not the unit — `sourcing.py:241`
- §3.9 — revise — ambiguity — `manufacturer` is required but not persisted; filing is phase- and posture-free and always bumps `version` — `projects.py:229`
- §3.9 — revise — ambiguity — reinstall takes no body; non-`STORED` unit / non-`REINSTALL` phase → `ERR_INVALID_STATE`, both before the isolation check — `field.py:488`
- §3.9 — revise — **mismatch** — re-energizing a non-`ISOLATED` circuit answers `ERR_INVALID_STATE`, not `ERR_CIRCUIT_NOT_ISOLATED`; circuit check precedes phase check — `field.py:147`
- §3.9 — revise — ambiguity — re-inspection gate: shut when **any** governing jurisdiction has `reinspection_required` true — `services.py:287`
- §3.9 — revise — ambiguity — `settlement_note` is persisted on the project, written only when supplied — `projects.py:280`
- §4 — revise — ambiguity — trailing slash tolerated; `ERR_NOT_FOUND` 404 / `ERR_METHOD_NOT_ALLOWED` 405 / `ERR_INTERNAL` 500 outside §5; filter semantics — `app.py:36`, `app.py:18`

**Notes on what needed no change**: the full role/authorization matrix in §4 matches `middleware.endpoint` decorators exactly; all posture rules, the cost/fee/credit/tolerance/spread/warranty formulas and their rounding placements, the ledger identity transfers, all phase-advance guards and trigger points, and the §2.11 precedence order all already pin their implementation behavior uniquely.

**Orchestrator verification:** `PRD_COMPLETED.md` present, 455 lines / 96,305 chars; `diff` against `PRD.md` shows 80 changed lines = 40 in-place 1-for-1 replacements, confirming no sections or paragraphs were added and the document tail (§5 error catalogue) is intact. Pipeline complete.
