# Worklog — task_2533_vote_by_mail_ballot_processing_signature_verification

## Step 1: Create task directory — 2026-09-03T06:48:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2533_vote_by_mail_ballot_processing_signature_verification` and its `workspace/` subdirectory. Index 2533 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was auto-allocated (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T08:22:00.000Z

All three scaffold artifacts for task 2533 are complete and lint-clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2533_vote_by_mail_ballot_processing_signature_verification/`)

| File | Lines | Content |
|---|---|---|
| `SCAFFOLD.yaml` | 2552 | §1.0–§1.7: scenario (verbatim), `api_prefix: /vote-by-mail`, complexity profile, 15 entities, 13 state machines (parallel shape: ReturnEnvelope carries three independent dimensions), 2 `concurrency_rules`, 9 calculations, 46 validations (priority 1→12), 68 endpoints, 46 errors, 5 roles. No `scaffold_*_design` keys. |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2135 | single key `scaffold_difficulty_design`; 9 rule_ids × 2 = 18 instances. |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3050 | single key `scaffold_corner_design`; 90 instances across all 9 claim-extraction-guide sections — entities 12, state_machines 16, calculations 11, validations 27, endpoints 6, errors 7, rbac 6, cross_cutting_layers 4, consistency_model 1 (71 with full `test_recipe`, 19 `excluded_because` stubs citing §1.8 by name). |

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2533_vote_by_mail_ballot_processing_signature_verification/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2533_vote_by_mail_ballot_processing_signature_verification/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2533_vote_by_mail_ballot_processing_signature_verification/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  1370

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Verification beyond lint
- Names unique across the union of both design files (90 + 18, zero collisions); every `excluded_because.difficulty_instance` resolves to a real §1.8 name; no stub carries a `test_recipe`; every non-stub has `claim_type` + `grounds`.
- Placeholder closure checked programmatically: 0 unbound `${var}` in payloads, paths, `as_user_id`, or asserts in either file.
- Error triggerability: all 46 error ids in §1.6 are now reachable from at least one instance.
- All formula-derived asserts are pre-computed literals (postage 141/197/253/591; confidence 0.8000/0.6000; `training_expires_at 2027-06-01T00:00:00Z`; `cure_deadline_at 2026-11-19T20:00:00Z`; USPS grace boundaries 2026-11-10T20:00:00Z / :01Z).
- Long setup chains are shared via ~47 YAML anchors, so each of the 90 instances is reachable from an empty DB using only declared endpoints.

## SCAFFOLD.yaml fixes forced by the §1.9 audit (this is the §1.5 iteration §1.9 is meant to produce)
1. `TransparencyLogEntry.event_type` enum was missing `REQUEST_LOGGED`, which `POST /ballot-requests` emits — added.
2. `ERR_DUPLICATE_ENVELOPE_FOR_PACKET` was unreachable (the priority-6 packet-state rule fired first once a packet became `RETURNED`); the priority-6 check now admits `{MAILED, RETURNED}` for intake so the priority-9 duplicate rule can fire.
3. `canvass-sweep` response counters were ambiguous (would `sequestered_envelope_count` include cure-expiry sequestrations?); added a side-effect line defining each counter as "what THIS sweep changed", making the sweep asserts falsifiable.
4. `scenario:` re-emitted as a single-paragraph literal block so it now byte-matches the assigned text exactly (previously line-folded).

The hard constraint held throughout: nothing under any sibling `tasks/task_*/` was listed, read, or grepped — only the scenario text plus `skills/prd-bench-scaffold-generator/` (SKILL.md, claim-extraction-guide.md, scaffold_lint.py).

## Step 3: Copy shared files — 2026-09-03T08:23:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T08:38:00.000Z

PRD generation is complete and all three Hard Contracts pass.

**Output:** `workspace/PRD.md` — **479 lines**, 30 headings, built across 9 chunked `cat >>` appends (never a single giant Write).

**Isolation constraint honoured:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced at any point.

**Truncation verification:** `wc -l` = 479; `tail -40` shows the file ending on the final row of the §5 error table (`| ERR_POSTAGE_BUDGET_EXCEEDED | 402 |`) — a completed section, not mid-sentence. Every planned heading is present (grep confirmed).

**Section list (30 headings)**
- `# Vote-By-Mail Processing API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` -> 2.1 RBAC · 2.2 API Response Structure (byte-identical verbatim copy, incl. its two `####` sub-headings) · 2.3 Pagination and Collection Filtering · 2.4 Common Record Properties and the Logical Election Clock · 2.5 Election Posture as the Master Gate · 2.6 Path Identifier Resolution Order · 2.7 Stale-View Protection on Voter and Envelope Writes · 2.8 Numeric Precision · 2.9 Cascade Discipline and Compensating Actions · 2.10 Segregation of Duties · 2.11 Ballot Accountability and the Conservation Invariants · 2.12 Transparency Logging and the Secrecy Invariant · 2.13 Rejection Precedence
- `## 3. Business Logic & Workflows` -> 3.1 Election registration and statutory calendar · 3.2 Ballot requests, address verification, permanent absentee list · 3.3 Building/sealing/dispatching the mail · 3.4 Return envelopes and timeliness · 3.5 Signature comparison, certification, escalation · 3.6 Cure notices, evidence, propagated cure deadline · 3.7 Observer access, challenges, adjudication · 3.8 Remaking damaged and duplicate ballots · 3.9 Separation, counting, canvass checkpoint
- `## 4. Endpoint Definitions` (68 rows, generated programmatically from the scaffold)
- `## 5. Error Code Catalogue` (46 rows, generated programmatically)

**Contract 1 — Field-Name Coverage: PASS.** 492 backtick tokens extracted. `entities[].fields` 137/137 · `request_body` 69/69 · `query_params` 29/29 · computed response keys 24/24 · errors 46/46 · roles 5/5. Zero missing.

**Contract 2 — Rule Coverage: PASS.** All 46 `validations[]` error IDs present with the full 12-level priority ladder reproduced verbatim in §2.13 (categories and ordering match the scaffold exactly); both `concurrency_rules[]` OCC rejections in §2.7 with their 412 statuses; all 61 `state_machines[].transitions[]` target states present (including the three parallel `ReturnEnvelope` dimensions and all four cyclic sub-machines); all 9 `calculations[]` fully transcribed with every numeric constant present as a literal (the only "absent" tokens were internal constant *names* like `POSTAGE_TIER_1_CENTS`, deliberately expanded into prose values, plus the algorithm-internal outcome labels `ESCALATE_LEAD`/`REJECT_NO_CURE`, rendered as "escalates with a lead restriction" / "rejection without cure"); all 37 endpoints with `side_effects` covered — a field-mention sweep found only `event_type` living in §2.12 rather than §3, which is intentional; 144 UPPER_SNAKE scaffold tokens checked, zero state/enum/error values missing; sibling-branch symmetry verified in prose for all 8 branch groups (NCOA cleared/failed, batch cancel from DRAFT vs SEALED, ESTIMATED/ACTUAL postage, preliminary/final timeliness, CURE/DEFICIENT, SUSTAIN/OVERRULE, remake complete/void, plain vs lead-restricted escalation); §5 HTTP statuses match `errors[].http` on all 46 rows with zero drift.

**Contract 3 — §3 Path Purity: PASS.** 973 backtick tokens in the `## 3.` -> `## 4.` slice: 0 `/`-leading tokens, 0 bare HTTP-method tokens, 0 method+path combos.

Three scaffold self-contradictions were resolved 2-of-3 and written consistently: cure-notice issuance requires posture exactly `RECEIVING` (CANVASS_LOCKED blocks it); the separation challenge gate is "anything other than `CHALLENGED`"; envelope intake accepts packets in `MAILED` or `RETURNED` so a re-scan falls through to the priority-9 duplicate rule. Two cosmetic fixes were applied after the contract sweep: digit-group spaces normalised (`86 400`->`86400`, `1 460`->`1460`) so no numeric literal can be misparsed, and blank lines inserted before six headings.

**Orchestrator truncation check (independent):** confirmed 479 lines, §4 endpoint table complete, §5 error table complete with all 46 rows, file ends at a real section boundary. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T09:30:00.000Z

Implementation complete and verified.

## Output: `workspace/implementation/`

| File | Lines |
|---|---|
| `start.sh` (executable, guarded pip install, `exec python3 app.py`) | 10 |
| `requirements.txt` (`Flask==3.0.3`) | 1 |
| `app.py` | 110 |
| `constants.py` | 104 |
| `db.py` | 136 |
| `errors.py` | 108 |
| `lookups.py` | 160 |
| `middleware.py` | 208 |
| `response.py` | 82 |
| `routes/elections.py` | 231 |
| `routes/voters.py` | 155 |
| `routes/reviewers.py` | 83 |
| `routes/requests.py` | 274 |
| `routes/mailing.py` | 302 |
| `routes/envelopes.py` | 321 |
| `routes/reviews.py` | 152 |
| `routes/cures.py` | 201 |
| `routes/remakes.py` | 282 |
| `routes/observers.py` | 190 |
| `routes/misc.py` | 41 |
| `services/accountability.py` | 142 |
| `services/signature.py` | 216 |
| `services/cure.py` | 58 |
| `services/cascade.py` | 55 |
| `services/postage.py` | 50 |
| `services/timeliness.py` | 46 |
| `services/election_flow.py` | 27 |
| `services/logbook.py` | 26 |
| `services/posture.py` | 23 |
| **Total Python** | **3,783** |

## Endpoints: 68 / 68 declared

Programmatic diff of the Flask URL map against the SCAFFOLD `endpoints` table (method + path, params normalized): **68 declared, 68 implemented, 0 missing, 0 extra.**

## Verification performed

- `python -m py_compile` on all 29 `.py` files -> all parse.
- **Smoke boot**: `PORT=18536 bash start.sh` backgrounded, `GET /vote-by-mail/elections` -> `200` with an empty `data` array and correct `meta` (`api_request_id` `req_` prefix, 3-digit timestamp, `limit`/`offset`/`total_count`/`has_more`), then killed. Repeated cleanly on three separate fresh boots (ports 18533/18535/18536) — no carry-over state, store empty every time.
- **Full happy-path integration run** (live server): election -> voter -> 3 reviewers -> ballot request -> address verification `MATCH_SAME` -> approve -> batch -> packet -> seal -> dispatch (auto `PRE_MAIL->MAILING`) -> envelope intake (auto `MAILING->RECEIVING`) -> signature review round 1 -> `MATCH` decision (envelope `ACCEPTED`, confidence 0.95) -> observer session -> check-in -> challenge -> `OVERRULE` (custody round-trips `SEALED->SEQUESTERED->SEALED`) -> remake open/complete/void -> accountability read -> clock advance + rewind rejection (422) -> transparency log (12 entries, per-election `sequence` 1..12, correct `subject_entity` per event) -> canvass sweep. All 28 assertions passed. Postage for a 30 g domestic same-address packet = 197 cents (129 outbound + 68 prepaid return); `attributable_ballot_count` conserved at 1 across remake complete->void while `envelopes_received_count` stayed at 2, per the §2.11 conservation invariant.
- **Cure-path integration run**: `MISSING_SIGNATURE` -> `CURE_REQUIRED` -> notice issued (`cure_deadline_at` = 2026-11-19T20:00:00Z, `canvass_days_at_issue` 17, `open_cure_count_at_issue` 1) -> duplicate notice 409 -> unsigned evidence -> `CURE` refused 409 -> `DEFICIENT` (back to `ISSUED`, `deficiency_count` 1, deadline not extended) -> signed evidence -> `CURE` (envelope `ACCEPTED`, `open_cure_count` 0). Cure-evidence rows correctly expose only `id` + `created_at` (no `updated_at`/`version`) per PRD §2.4. Observer geometry verified: overlapping same-party -> `ERR_OBSERVER_PARTY_SLOT_CONFLICT`, touching endpoints -> 201, revoke then check-in -> 409.
- **RBAC audit**: all 68 endpoints × 5 roles probed against the scaffold `roles:` lists — **0 mismatches** (403/`ERR_ROLE_FORBIDDEN` exactly where and only where undeclared).
- **Auth audit**: all 68 endpoints with no headers -> 401 `ERR_UNAUTHENTICATED`, 0 mismatches.
- Framework fallthroughs: unknown path -> 404 `ERR_RECORD_NOT_FOUND`; wrong method -> 405 `ERR_INVALID_REQUEST`; malformed JSON body -> 400 `ERR_INVALID_REQUEST`.
- **Storage audit**: grep for `seed|sqlite|json.dump|shelve|pickle|open(` finds only the two docstring lines saying nothing is seeded. Storage is plain module-level dicts in `db.py`; no disk artifacts. `__pycache__` directories removed after compiling.

The hard constraint was honored throughout: `test_suite/`, `test_helpers/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, and all sibling task directories were never read, listed, globbed, or grepped. Everything derives from `PRD.md`, `SCAFFOLD.yaml`, and `INSTRUCTION.md`, with PRD prose taking precedence on the two conflicts found (cure-issuance posture is exactly `RECEIVING`, not `{RECEIVING, CANVASS_LOCKED}`; the reviewer selector raises `ERR_NO_ELIGIBLE_REVIEWER` rather than `ERR_SEGREGATION_OF_DUTIES` on an empty candidate set).

**Orchestrator note on Step 5/6 launch:** the two Agent calls were issued in back-to-back messages rather than a single message, so Step 6 lost the *physical* isolation of `test_suite/` not yet existing. Compensated by an explicit hard prohibition in the Step 6 prompt against reading `test_suite/`, `test_helpers/`, either design yaml, or any sibling task; the subagent confirmed compliance in its summary.

## Step 5: Generate unit tests — 2026-09-03T09:48:00.000Z

Final proof sweep is complete and green.

## Deliverables

**`test_helpers/` — 9 files, 2,084 lines**

| file | lines |
|---|---|
| `test_helpers/types.py` | 549 |
| `test_helpers/fixtures.py` | 612 |
| `test_helpers/api_client.py` | 267 |
| `test_helpers/assertions.py` | 238 |
| `test_helpers/factories.py` | 166 |
| `test_helpers/api_errors.py` | 105 |
| `test_helpers/constants.py` | 74 |
| `test_helpers/test_users.py` | 38 |
| `test_helpers/__init__.py` | 35 |

**`test_suite/` — conftest + 16 numbered files, 6,005 lines, 138 test functions**

`conftest.py` 39 · `test_01_dual_variant_and_formula.py` 446 (14 tests) · `test_02_state_machine_and_cascade.py` 555 (13) · `test_03_validation_priority_conflicts.py` 267 (7) · `test_04_boundary_precision.py` 265 (7) · `test_05_cross_entity_state.py` 246 (7) · `test_06_temporal_overlap.py` 308 (8) · `test_07_compensating_invariants.py` 349 (8) · `test_10_entity_surfaces.py` 495 (13) · `test_11_state_machine_edges.py` 521 (10) · `test_12_calculation_edges.py` 378 (7) · `test_13_validation_refusals.py` 551 (11) · `test_14_endpoint_behaviours.py` 321 (6) · `test_15_error_catalogue.py` 281 (7) · `test_16_role_boundaries.py` 286 (6) · `test_17_concurrency_and_consistency.py` 204 (3) · `test_18_validation_refusals_continued.py` 493 (11)

## Verification results

- `ast.parse` + `python -m py_compile` over all 26 generated `.py` files: **pass**.
- `pytest --collect-only`: **161 cases collected, 0 errors** (138 functions; the extra 23 come from `@pytest.mark.parametrize` in files 01, 04, 06, 11, 12, 15). Helper imports and fixtures resolve post-patch.
- Design-tag validator: index holds **18 difficulty / 71 non-stub corner / 19 stub** instances. 138 tests carry exactly **138** `Design:` lines — no unknown tags, no tags pointing at stubs, no untagged or dual-tagged tests. Every difficulty instance has 3–4 tests (floor 2); every non-stub corner instance has 1–2 (floor 1). All 19 stub cross-references resolve to real difficulty instances.
- Citation audit: **0 of 138** tests lack a verbatim-grep-able PRD.md citation line.
- Structural audit: **0 issues** — exactly one `Design:` line per test, always last in the docstring; no `scaffold` mentions, no `skip`/`xfail`, no `unittest`, no TODO/placeholder, no design-doc section references.

## Skipped design instances

**None.** All 18 difficulty and all 71 non-stub corner instances passed the PRD-first two-condition filter and were translated.

## Findings to reconcile upstream (design yaml vs PRD; tests follow the PRD)

1. `Corner/endpoints/sustained_challenge_sequesters_the_envelope_and_refers_the_voter` — yaml asserts `attributable_ballot_count == 1`, but the PRD derives **0** for a SEQUESTERED + REJECTED envelope. Test asserts 0.
2. Two yaml instances assert `mailing_address_snapshot == null`; the PRD freezes the residence address into the snapshot. Tests assert the frozen address.
3. One instance expects `response_type == "election"`; the PRD's catalogue allows only `object`/`array`. Assertion dropped.
4. One instance asserts `OBSERVER_SESSION_OPENED total_count == 0`; the PRD emits the event, so the test asserts 1.

Five helper defects surfaced by the sub-workers were verified against PRD.md and patched: canvass-sweep role -> `ElectionsAdmin` (PRD L364), observer-session creation -> `ElectionsClerk` (L419), challenge outcome `OVERRULED` -> `OVERRULE` (L307), `similarity_score` now omitted for `MISSING_SIGNATURE`/`ABSTAIN` (L249), and `ReviewDecision`/request-status enums corrected (dropped invented `ESCALATE_LEAD`, added `ADDRESS_CLEARED`/`SAME_ADDRESS`, added `ChallengeOutcome`/`CureOutcome`).

The isolation constraint held throughout: neither I nor any worker read `workspace/implementation/` or any sibling task directory.

## Step 7: Run tests and iterate — 2026-09-03T09:58:00.000Z

All 8 rounds passed on the first sweep, and the integrity checks confirm it is a genuine green rather than a masked one.

## Summary

**Iterations run: 1** (single 8-round parallel sweep, all rounds green — no fix/delete cycle was needed).

**Tests deleted: none.** No test failed in any of the 8 rounds, so no test entered the STEP 1 coverage / unique-derivability filter.

**Fixes applied to `test_helpers/`: none.** No fixture, factory, or role-header defect surfaced.

**Fixes applied to `implementation/`: none.** No implementation defect surfaced.

### Final per-round results

| Round | passed / total | failed | errors | skipped | duration |
|---|---|---|---|---|---|
| 1 | 161 / 161 | 0 | 0 | 0 | 290s |
| 2 | 161 / 161 | 0 | 0 | 0 | 290s |
| 3 | 161 / 161 | 0 | 0 | 0 | 290s |
| 4 | 161 / 161 | 0 | 0 | 0 | 290s |
| 5 | 161 / 161 | 0 | 0 | 0 | 290s |
| 6 | 161 / 161 | 0 | 0 | 0 | 290s |
| 7 | 161 / 161 | 0 | 0 | 0 | 290s |
| 8 | 161 / 161 | 0 | 0 | 0 | 290s |

All eight `results.${i}.json` files are present on disk and are complete JSON, at `workspace/implementation/results.{1..8}.json` (~56 KB each, written 09:40).

### Validation that the green is real, not masked

I checked the per-test records rather than trusting only the headline counters — worth noting because the results schema keys test outcomes as `status`, not `outcome`, so a naive filter silently reports every test as failing. Reading `status` directly: 0 non-`passed` entries across all 8 rounds.

- **No suppression**: 0 occurrences of `pytest.mark.skip`, `skipif`, or `xfail` anywhere in `test_suite/` or `test_helpers/`; `skipped == 0` in every round.
- **Collection is complete**: 138 test functions across 16 suite files expand to 161 cases via `@pytest.mark.parametrize`, matching `total == 161` — no silently uncollected file.
- **Storage constraint honored**: 0 hits for `sqlite`, `json.dump`, `shelve`, `pickle`, or `/tmp/` in `workspace/implementation/`; storage is in-memory dicts only.
- **Sweep was not SIGTERM'd**: 0 occurrences of `Terminated` in `workspace/sweep.log`, confirming the `setsid nohup` wrapper held and all 8 rounds ran to natural completion (identical 290s durations reflect the concurrent launch, not a shared kill).

The task exits clean on the first iteration: the implementation and both layers of the test artifact are mutually consistent, and the 8-round parallel sweep surfaced no timing-sensitive flakiness.

**Orchestrator independent re-verification (not taken on faith):** re-read all 8 `results.*.json` from disk directly. Each reports `passed=161 total=161 failed=0 skipped=0`, and a per-test `status` histogram over each file yields `{'passed': 161}` with no other status value. `grep -c Terminated workspace/sweep.log` = 0. Artifacts confirmed present, so this is not the known failure mode where a Step 7 agent claims a clean sweep having left no results files behind.

## Step 8: Finalize PRD — SKIPPED — 2026-09-03T09:59:00.000Z

Skip condition from the skill met exactly: Step 7 exited on the **first** 8-round sweep with **0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes** — zero iterations beyond the baseline. There is therefore no `<step_7_diff>` to hand off and no Step-7-identified PRD-silence site to patch: `PRD.md` already determined every behavior the test suite exercised. No subagent was spawned and no `PRD_FINALIZED.md` was produced. Step 9 consequently takes `workspace/PRD.md` as its source, per the skill's input rule ("Start from `workspace/PRD_FINALIZED.md` if Step 8 produced it; otherwise from `workspace/PRD.md`").

Note this does NOT imply the PRD is complete — a green first sweep only means the tests found no divergence, and the test suite exercises a subset of implementation behavior. Residual PRD silences that the implementation resolved at generation time are exactly what Step 9's full PRD-vs-implementation scan exists to close, and Step 9 always runs.

## Step 9: Complete PRD — 2026-09-03T10:35:00.000Z

**Orchestrator decision:** Step 9 was run as **three sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md` rather than one monolithic scan. Reason: a single subagent asked to walk 29 implementation files exhaustively reliably under-scans and can emit a `PRD_COMPLETED.md` byte-identical to its source, which is indistinguishable from "the PRD was already complete" but is actually a silent no-op. Partitioning bounds each pass's reading load and makes each pass's coverage auditable. Pass A copied `PRD.md` -> `PRD_COMPLETED.md` and edited it; Passes B and C edited the same file in place, each instructed not to revert prior passes' edits, and each required to read out-of-scope files when needed to satisfy the no-new-mismatch rule. Source was `PRD.md` (no `PRD_FINALIZED.md`, Step 8 skipped).

Partition:
- **Pass A** — `app.py`, `middleware.py`, `response.py`, `errors.py`, `db.py`, `constants.py`, `lookups.py`, `routes/misc.py`, `routes/elections.py`, `routes/voters.py`, `routes/reviewers.py`, `services/posture.py`, `services/election_flow.py`, `services/logbook.py`
- **Pass B** — `routes/requests.py`, `routes/mailing.py`, `routes/envelopes.py`, `services/postage.py`, `services/timeliness.py`, `services/cascade.py`
- **Pass C** — `routes/reviews.py`, `routes/cures.py`, `routes/remakes.py`, `routes/observers.py`, `services/signature.py`, `services/cure.py`, `services/accountability.py`

### Totals across the three passes

`PRD.md` 479 lines / 100,591 chars -> `PRD_COMPLETED.md` 479 lines / **115,519 chars (+14,928)**. **56 edits: 44 ambiguity-pins, 12 mismatch-revisions.** Every edit is an in-place line revision — `diff` reports 0 add/delete hunks, so no section, paragraph, or table row was added or removed.

---

### PASS A — 18 edits (13 ambiguity-pins, 5 mismatch-revisions)

- §2.1 — revise — mismatch — auth headers: whitespace-only header value is also `ERR_UNAUTHENTICATED`, not just absent/empty — `middleware.py:31-37`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `response.py:13-14`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; empty-string param falls back to default — `middleware.py:163-183`
- §2.3 — revise — mismatch — default ordering ties broken by service creation order; transparency-log `sequence` is per-election so a multi-election listing is in global append order, not globally `sequence`-sorted — `db.py:133-135`, `routes/misc.py:26-29`, `services/logbook.py:8-11`
- §2.3 — insert — ambiguity — filter matching semantics: bool matches lowercase `true`/`false`, int compared numerically (unparseable matches nothing), null stored value never matches, empty-string filter treated as absent, unlisted query params ignored — `middleware.py:187-208`
- §2.4 — insert — ambiguity — emitted 3-digit fractions truncate rather than round; caller datetimes with an offset are converted to UTC and offsetless ones read as UTC — `db.py:71-98`
- §2.8 — revise — mismatch — whole-second normalisation of both comparison sides happens only in the §3.4 timeliness evaluation; all other deadline comparisons use the clock at full precision against the stored (already whole-second) instant; supplied `return_deadline_at` is truncated on storage — `services/timeliness.py:18-28`, `routes/elections.py:44`, `routes/misc.py:38`
- §2.11 — insert — ambiguity — accountability also recomputed on posture advance and on every election read/list; recompute touches the election only when a figure actually changed; `returned_packet_count` and `accountability_delta` are read-only (not election fields) — `services/accountability.py:56-83`, `routes/elections.py:80-100`
- §2.12 — insert — ambiguity — `election_id` is null for events not scoped to an election (enrollment reinstatement), with their own `sequence` series — `services/logbook.py:8-11`, `routes/voters.py:131-132`
- §2.13 — insert — ambiguity — absent/empty body read as `{}`; non-JSON or non-object body is `ERR_INVALID_REQUEST` — `middleware.py:49-62`
- §3.1 — insert — ambiguity — dates strict `YYYY-MM-DD`, echoed verbatim; `postmark_grace_days`, `cure_window_days`, `postage_budget_cents` each min 0 — `routes/elections.py:36-42`, `middleware.py:141-152`
- §3.1 — revise — ambiguity — every `POSTURE_CHANGED` entry has `subject_entity` `Election` / `subject_id` the election id — `services/election_flow.py:11-19`
- §3.1 — revise — ambiguity — the four certification gates are checked against a freshly recomputed accountability picture — `routes/elections.py:120-133`
- §3.2 — revise — **mismatch** — `permanent_absentee_active` is written by the enrollment lifecycle (enrol / approval-enrol / reinstate -> true; suspend / remove -> false), not recomputed as "true exactly when an ACTIVE enrollment exists"; `provisional_ballot_eligible` is set only by the provisional-referral cascade (rejection-without-cure, sustained challenge, cure expiry) — not by every path that writes `signature_status = REJECTED` (remake void writes REJECTED without referring) — `routes/voters.py:89,128,153`, `services/cascade.py:25,41`, `routes/requests.py:172`, `routes/remakes.py:261`
- §3.2 — insert — ambiguity — direct enrolment has no duplicate check; "the voter's enrollment" means the most recently created row in the named status — `routes/voters.py:80-91`, `lookups.py:144-160`
- §3.9 — insert — ambiguity — the sweep runs in any posture except `CERTIFIED`, bumps `canvass_sweep_index` even when nothing changes, and attributes its `CURE_EXPIRED` / `PROVISIONAL_REFERRAL` entries to the acting admin rather than `system` — `routes/elections.py:139-190`
- §4 — insert — ambiguity — trailing slash equivalent to its absence — `app.py:47`
- §5 — insert — mismatch — framework responses outside the id/status pairing: unknown path -> 404 `ERR_RECORD_NOT_FOUND`; unsupported method -> 405 `ERR_INVALID_REQUEST` — `app.py:70-82`

Role sets, status codes, and the accountability-read field list for all 18 Pass-A endpoints were diffed against the §4 table and §3.9 and already matched exactly — no edits needed there.

---

### PASS B — 21 edits (17 ambiguity-pins, 4 mismatch-revisions)

- §2.5 — insert — ambiguity — enumerated the residual posture gate: every mutating election-scoped op not named in the paragraph is gated only against `CERTIFIED` (verified all 28 `posture.require*` callsites, incl. Pass C files) — `services/posture.py:14`
- §3.2 (verification result) — insert — ambiguity — request-state failure is `ERR_REQUEST_STATE_INVALID` and is checked *after* the PENDING check; `ncoa_result`/`verified_mailing_address`/`forwardable` are persisted verbatim in every branch; response is the updated verification — `routes/requests.py:239-247`
- §3.2 (two branches) — revise — **mismatch** — `MATCH_FORWARDABLE` overwrites `mailing_address_snapshot` unconditionally (null when omitted); on `NO_MATCH` `forwarding_class` is *never written*, so it keeps whatever a prior failed evaluation left, not necessarily `UNKNOWN` — `routes/requests.py:256-266`
- §3.2 (cascade link 2) — insert — ambiguity — increment and suspension are two separate mutations -> enrollment `version` +2 on a suspending pass — `services/cascade.py:19-25`
- §3.2 (cascade link 3) — insert — ambiguity — `ENROLLMENT_SUSPENDED` records the acting `ElectionsClerk`, not `system` (both heads are clerk-driven) — `services/cascade.py:28-36`
- §3.2 (address re-check) — insert — ambiguity — answers 201 with the new verification; leaves request status/`forwarding_class` and existing verifications untouched — `routes/requests.py:204-205`
- §3.2 (approval) — insert — ambiguity — approval-created enrollment field initialisation; response is the request; no log entry — `routes/requests.py:160-175`
- §3.2 (request create) — insert — ambiguity — the PENDING verification's four other fields start null — `routes/requests.py:23-34`
- §3.3 (add packet) — revise — **mismatch** — `batch_sequence` is `packet_count`+1 *as freshly recomputed*, so a spoiled packet's number is reused and it is not always creation order; `packet_serial` zero-pads to exactly four digits — `routes/mailing.py:108,118`
- §3.3 (add packet) — insert — ambiguity — `packet_count` recomputed on every packet status change, before batch state gates, and on single/list reads, written only when changed; no rule limits a request to one packet — `services/accountability.py:141-152`, `routes/mailing.py:65,75,92`
- §3.3 (seal) — insert — ambiguity — `packet_count < 1` is reported as `ERR_BATCH_STATE_INVALID` — `routes/mailing.py:140-141`
- §3.3 (dispatch) — insert — ambiguity — the automatic `POSTURE_CHANGED` entry is appended before `BATCH_DISPATCHED` — `routes/mailing.py:200-209`
- §3.3 (cancel) — insert — ambiguity — the batch's own `estimated_postage_cents` and `sealed_at` are retained, never zeroed by the release — `routes/mailing.py:226-238`
- §3.4 (intake payload) — insert — ambiguity — a `postmark_date`/false `postmark_legible` on a `DROPBOX`/`IN_PERSON` intake is stored but never consulted; no validation error — `routes/envelopes.py:40-41`, `services/timeliness.py:22-25`
- §3.4 (intake effects) — revise — **mismatch** — packet left alone when already `RETURNED`; auto-advance fires whenever the posture is still `MAILING` (not "if this is its first intake"); `POSTURE_CHANGED` precedes `ENVELOPE_INTAKE`; `preliminary_timeliness` is written as part of the create, so the 201 body carries `version` 1 — `routes/envelopes.py:78-96`
- §3.7 (adjudication) — insert — ambiguity — `challenge_findings` is a required non-empty string written in both branches — `routes/envelopes.py:179,188`
- §3.7 (sustain) — insert — ambiguity — `PROVISIONAL_REFERRAL` records the adjudicating `CanvassSupervisor` and lands after `CHALLENGE_ADJUDICATED` — `routes/envelopes.py:194-209`
- §3.9 (separation guards) — insert — **mismatch** — separation is the one operation where the posture check precedes identifier resolution, so `ERR_ELECTION_POSTURE_FORBIDS` wins over `ERR_ENVELOPE_NOT_FOUND` (explicit exception to §2.13) — `routes/envelopes.py:265-267`
- §3.9 (per-envelope gates) — insert — ambiguity — an `UNTIMELY` `final_timeliness` reports `ERR_ENVELOPE_CUSTODY_STATE_INVALID`; null passes; gates applied envelope-by-envelope in array order — `routes/envelopes.py:270-278`
- §3.9 (run response) — insert — ambiguity — `secrecy_pool_size` = submitted array length incl. repeats; `separated_count` = distinct moved, and it is the figure the min-pool guard measures — `routes/envelopes.py:283-291,312-321`
- §3.9 (count) — insert — ambiguity — the `final_timeliness` gate reports `ERR_ENVELOPE_CUSTODY_STATE_INVALID` — `routes/envelopes.py:245-246`

Pass B cross-checks: `services/postage.py` and `services/timeliness.py` were already fully pinned by §2.8/§3.3/§3.4 — no edits needed. For the no-new-mismatch rule the §2.5 enumeration was verified against every `posture.require*` callsite including `reviews.py`/`cures.py`/`remakes.py`/`observers.py`, and `cascade.undeliverable_event` confirmed reachable only from Pass B files while `refer_to_provisional`'s other caller (`routes/elections.py:185`) already carries Pass A's `ElectionsAdmin` attribution — so neither actor-role claim conflicts. Pass B flagged one item into Pass C's scope: `services/signature.py:145-151` performs the rejection-without-cure referral inline and appends **no** `PROVISIONAL_REFERRAL` entry, unlike the other two heads.

---

### PASS C — 19 edits (14 ambiguity-pins, 3 mismatch-revisions; 2 bullets cover 2 subjects each)

- §3.5 — insert — ambiguity — envelope `PENDING_REVIEW` gate is bucket 6 of §2.13 and so is evaluated *ahead of* the assigned-reviewer identity and training checks, despite the prose naming them first — `routes/reviews.py:105-120`
- §3.5 — insert — ambiguity — an `ABSTAIN` neither requires nor forbids `similarity_score`; a score supplied with one is accepted and stored verbatim — `routes/reviews.py:89-98,124`
- §3.5 — revise — **mismatch** — confidence is null because `MISSING_SIGNATURE`/`ABSTAIN` are *never scored*, not because they "carry no `similarity_score`" (an ABSTAIN may carry one) — `services/signature.py:24-27`
- §3.5 — insert — ambiguity — resolution runs in the same request, so a `SIGNATURE_ESCALATION` entry lands *after* the `SIGNATURE_DECISION` entry; the response is the updated review, not the envelope — `routes/reviews.py:140-152`
- §3.5 — revise — ambiguity — round two has a **sixth** case: two `ABSTAIN` decisions escalate with a lead restriction (the round's fallback for anything the five named cases miss) — `services/signature.py:112-118`
- §3.5 — insert — ambiguity — an escalation of either flavour leaves `resolved_signature_confidence` exactly as it stood — `services/signature.py:168-170`
- §3.5 — revise — **mismatch** — rejection-without-cure fires only on a `SIGNATURE_MISMATCH` reason; the `MISSING_SIGNATURE` override still earns a cure on a replacement at any round — `services/signature.py:133-138`
- §3.5 — insert — ambiguity — **(Pass B hand-off resolved)** this referral head sets `resolved_signature_confidence` from the dispositive review, leaves an already-`SEQUESTERED` envelope alone, recomputes `rejected_envelope_count`, and appends **no** `PROVISIONAL_REFERRAL` entry — the one silent head of the three — `services/signature.py:139-152`
- §3.6 — revise — **mismatch** — notice `reason_code` may be **null**, namely when the envelope holds no review outcome of its own; a remake replacement inheriting `CURE_REQUIRED` has no `_cure_reason_code`, so a notice issued on it gets null — `routes/cures.py:41-44` (cause: `routes/remakes.py:176`)
- §3.6 — insert — ambiguity — the three frozen deadline values are written as part of row creation, so a fresh notice answers 201 at `version` 1; `CURE_ISSUED` names the notice as subject — `routes/cures.py:54-69`
- §3.6 — insert — ambiguity — on `CURE`, a missing or unsigned newest evidence row yields `ERR_CURE_STATE_INVALID`, checked before the deadline test; a `deficiency_reason_code` sent with `CURE` is ignored — `routes/cures.py:147-155`
- §3.6 — insert — ambiguity — on `DEFICIENT`, `deficiency_reason_code` lands null when omitted — `routes/cures.py:132-173`
- §3.7 — insert — ambiguity — the scheduling `OBSERVER_SESSION_OPENED` entry records the booking principal's own role; scheduling performs no identity check, so an `Observer` may book in a colleague's name — `routes/observers.py:61,105-113`
- §3.7 — insert — ambiguity — check-in identity mismatch yields `ERR_ROLE_FORBIDDEN`, evaluated *after* the session-status gate rather than at §2.13's authorisation step — `routes/observers.py:142-145`
- §3.7 — insert — ambiguity — `revocation_reason_code` is a required non-empty free-form string — `routes/observers.py:169`
- §3.8 — revise — ambiguity — `remade_serial` resolution: body value wins over the one carried since opening; absence yields `ERR_INVALID_REQUEST`, checked *after* the four state/posture gates rather than with §2.13's schema bucket — `routes/remakes.py:149-151`
- §3.8 — insert — ambiguity — the replacement envelope opens with `review_round_count` 0 and `resolved_signature_confidence`/`separation_run_sequence`/`challenge_reason_code`/`challenge_findings` all null, so it inherits the signature verdict but no review history and gets a fresh three-round ceiling; completion answers 200 with the record, never the envelope — `routes/remakes.py:165-189,232`
- §3.8 — insert — ambiguity — voiding does **not** undo completion's clean-ups: a withdrawn notice stays `WITHDRAWN`, a voided review stays `VOIDED` and its reviewer's `active_review_count` is not restored — `routes/remakes.py:258-270`
- §3.8 — insert — ambiguity — `voided_reason_code` is a required non-empty free-form string — `routes/remakes.py:239`

Nothing needed changing for `services/accountability.py` — every figure, the `ELECTION_KEYS` exclusion of `returned_packet_count`/`accountability_delta`/`provisional_referral_count`/money, the write-only-if-changed rule, the 15-field accountability read, and `recompute_batch`'s status set were already pinned uniquely by §2.11/§3.1/§3.9. (`postage_totals` is dead code — no callsite — so no PRD claim attaches to it.)

---

### Final integrity check (Pass C, then re-verified independently by the orchestrator)

- 479 lines / 115,519 chars vs `PRD.md` 479 / 100,591 — identical line count, so no structural drift
- `##` sections **5/5**; `###` subsections **22/22**; heading-line `diff` vs `PRD.md` identical
- §4 endpoint table **68 data rows**; §5 error table **46 data rows** — both match `PRD.md` exactly
- `tail` ends at `| ERR_POSTAGE_BUDGET_EXCEEDED | 402 |`, the real last row of the §5 table
- `diff PRD.md PRD_COMPLETED.md` add/delete hunks: **0** — all changes are in-place line revisions
- **`cmp` confirms the two files are NOT identical** (106 differing lines reported by `diff`, i.e. 53 revised line-pairs) — so the scan genuinely ran and did not silently no-op

## Pipeline complete — 2026-09-03T10:36:00.000Z

Steps 1-7 and 9 executed; Step 8 skipped on its documented skip condition. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files), `test_suite/` (conftest + 16 files, 161 collected cases), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (29 Python files + `start.sh`, 68/68 endpoints), and `workspace/implementation/results.{1..8}.json` all at 161/161.
