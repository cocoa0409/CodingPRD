# Worklog — task_2694_municipal_clerk_records_ordinance_codification

## Step 1: Create task directory — 2026-09-04T08:04:18.119Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2694_municipal_clerk_records_ordinance_codification` and its `workspace/` subdirectory. Index 2694 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed (concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-04T09:26:45.610Z

Subagent summary (verbatim):

Done. `VERDICT: clean lint` on the first lint run after the corner file was completed.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2694_municipal_clerk_records_ordinance_codification/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2694_municipal_clerk_records_ordinance_codification/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2694_municipal_clerk_records_ordinance_codification/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    77
  §1.1 entities declared:     15
  §1.8 instances scanned:     24
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  886

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files (absolute paths, final line counts)

- `SCAFFOLD.yaml` — 3258 lines (no `scaffold_difficulty_design` / `scaffold_corner_design` keys present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2440 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3623 lines

## Domain model

`api_prefix: /clerk`; profile: primary `compliance_audit` / secondary `multi_party_negotiation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation]`, topology `hybrid`, state-machine shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, `difficulty_level: beyond_expert`.

- **15 entities**: Venue, Meeting, AgendaPacket, AgendaItem (`common_fields: false`, immutable), Motion, MinutesRecord, NumberSeries, LegislativeInstrument, PublicationNotice, CodeTitle, SupplementCycle, CodificationSubmission, PublicRecordsRequest, RecordSeries, DestructionBatch.
- **77 endpoints**, **10 state machines**, **12 calculations**, **35 validations** (priorities 1-96), **77 errors**, **7 roles** (CityClerk, DeputyClerk, PresidingOfficer, RecordsOfficer, CodificationEditor, Requester [`entity_backed:PublicRecordsRequest`], Anonymous), plus a logical-clock endpoint pinned at 2026-08-01T00:00:00Z.
- Key state machines: Meeting SCHEDULED->NOTICED->IN_SESSION->ADJOURNED (+CANCELLED); AgendaPacket DRAFT->POSTED->SUPERSEDED/WITHDRAWN; MinutesRecord DRAFT->SUBMITTED->APPROVED<->CORRECTION_PENDING (the cycle); LegislativeInstrument INTRODUCED->FIRST_READING_PASSED->ADOPTED_UNOFFICIAL->ADOPTED->(VETOED->VETO_OVERRIDDEN)->PUBLISHED->EFFECTIVE; SupplementCycle OPEN->LOCKED->CERTIFIED; CodificationSubmission PENDING->IN_REVIEW/CONFLICT_HELD->ACCEPTED/REJECTED/WITHDRAWN; DestructionBatch PROPOSED->CERTIFIED->RESCINDED; PublicRecordsRequest RECEIVED->...->CLOSED.
- Signature deep chains: the four-hop MINUTES_APPROVAL officialization cascade (minutes approve -> `result_official` bubble-up -> instrument numbering off NumberSeries -> DRAFT PublicationNotice), and the four-hop certify-publication->codification cascade (notice PUBLISHED -> effective-date variant -> CASCADE submission enrolment -> conflict pairing).
- 3 OCC rules (§1.2.1): `expected_meeting_version`, `expected_code_title_version`, `expected_minutes_version` -> 412 stale errors.

## §1.8 difficulty design — 9 rule ids / 24 instances

dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 4, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

## §1.9 corner design — 9 sections / 78 instances (68 with full recipes, 10 `excluded_because` stubs)

entities 12, state_machines 14, calculations 11, validations 10, endpoints 6, errors 12, rbac 5, cross_cutting_complexity_layers 7, consistency_model 1.

Error-catalog sweep: all **77/77** error ids are now triggerable across the two design files (0 uncovered), including the four chain-only ids — ERR_NUMBER_SERIES_EXHAUSTED (next_sequence 999 with two adopted ordinances -> atomic 422, nothing minted), ERR_PUBLICATION_COUNT_MISMATCH, ERR_PUBLICATION_INTERVAL_TOO_SHORT and ERR_NO_OPEN_SUPPLEMENT_CYCLE.

## Two defects found and fixed while finishing

1. `POST /clerk/meetings/{meeting_id}/agenda-packets` increments `Meeting.version`, so two instances written earlier (`a_fourth_packet_revision_on_one_meeting_is_refused`, `the_agenda_item_filter_isolates_one_packet_from_another`) reused a stale captured version for later revisions and would have returned 412 instead of the intended result. Both now re-read the meeting version between filings; the revision-limit instance additionally asserts `${err} != ERR_STALE_MEETING_VERSION`.
2. PyYAML cannot parse unquoted `[` inside a flow sequence — 59 `grounds:` lines (e.g. `endpoints[POST /clerk/venues]`) broke the parse; every grounds item is now double-quoted.

## Step 3: Copy shared files — 2026-09-04T09:27:09.397Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T09:44:00.000Z

Truncation guard (orchestrator): PRD.md is 494 lines / 98141 bytes; `tail -12` ends on the 77th and final row of the §5 Error Code Catalogue table (`| ERR_NO_OPEN_SUPPLEMENT_CYCLE | 409 |`), a genuine section boundary — not truncated. Section map confirms §1 Introduction, §2.1-§2.11, §3.1-§3.9, §4 Endpoint Definitions (77 rows), §5 Error Code Catalogue (77 rows) all present.

Subagent summary (verbatim):

PRD generated and all three Hard Contracts verified PASS.

**Output:** `workspace/PRD.md` — **494 lines**, no heredoc sentinels leaked, ends at a genuine section boundary.

**Last section heading:** `## 5. Error Code Catalogue` (line 412); final line is the table row `| \`ERR_NO_OPEN_SUPPLEMENT_CYCLE\` | 409 |`.

**Sections written**
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC (all 7 roles; `Requester` entity-backed via `PublicRecordsRequest`), 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Path Resolution and Referential Order, 2.7 Optimistic Concurrency on Parent Versions, 2.8 Segregation of Duties on Certification, 2.9 Arithmetic/Rounding/Money, 2.10 Mirrored and Derived Fields, 2.11 Order of Evaluation
- `## 3. Business Logic & Workflows` — 3.1 meetings/venues, 3.2 packets & notice clock, 3.3 convening/motions/vote arithmetic, 3.4 minutes & officialization cascade, 3.5 numbering & instrument lifecycle, 3.6 publication/invoice/certification cascade, 3.7 codification cycles & conflict precedence, 3.8 records requests (dual axis), 3.9 retention/custody/destruction
- `## 4. Endpoint Definitions` — 77 data rows, exactly 4 columns
- `## 5. Error Code Catalogue` — 77 data rows, exactly 2 columns

**Contract 1 — Field-Name Coverage: PASS**
`entities[].fields` 127/127 - request-body identifiers 84/84 - `query_params` 19/19 - `path_params` 14/14 - `fee_lines` sub-fields (`page_count`, `staff_minutes`, `delivery_medium`) 3/3 -> 247 required, 0 missing. Stricter re-pass: all 156 distinct identifiers appear as *standalone* backticked tokens (none only embedded in a larger token). Also 77/77 `errors[].id` and all entity enum values present.

**Contract 2 — Rule Coverage: PASS**
10 state machines / 55 transitions / 50 distinct states all narrated; 12 calculations all specified in natural language with every constant value present in prose (72/48/24/48 base notice hours, +168, +24, x1.0/x1.5, 4000-char threshold, 2 vs 1 insertions, 15-day deadline, 7-day gap, 500 and 2500 cents, 50000/150000 tiers at 0.00/0.05/0.10, 30-day lag + Sat+2/Sun+1 roll, 5 business days, 20 free pages, 15 vs 25 cents/page, 875 cents/quarter-hour, 2 free quarter-hours, electronic x0.5, commercial x1.20, ZONING 3 > CODE_AMENDMENT 2 > GENERAL 1 > EMERGENCY 0, 06-30 fiscal anchor, both conservation invariants); 35 validations — all 77 referenced error IDs appear in §1-§3 prose, not merely in the §5 table — including the three ordering exceptions (50-before-64, 40-before-80, 52-before-62); 3 OCC rules with their `expected_*` fields and 412s; 111 endpoint side-effect entries; both 4-hop cascades; caps 3/3/999; segregation of duties on both certifications; sibling-branch symmetry for `MINUTES_CORRECTION`; all `applies_to` scopes for legal hold/permanence.

**Contract 3 — §3 Path Purity: PASS**
955 backticked tokens in §3: 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations. All paths/methods confined to §1, §2 and the §4 table.

**Confirmed:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was inspected. Sources read were only `SKILL.md`, `section-2.2-response-structure.md`, and `SCAFFOLD.yaml`.

One process note: the initial Contract 1 checker reported ~117 false "missing" fields. Cause was the inline-backtick regex pairing being thrown off by the ``` fences in §2.2/§2.3 — stripping fenced blocks before extracting inline tokens fixed it. Worth baking into future contract-check scripts.

## Step 6: Generate implementation — 2026-09-04T10:40:00.000Z

Orchestrator note: the first Step 6 subagent was terminated early by a transient upstream API error, having written only `start.sh` and `requirements.txt`. Per the resume protocol the SAME agent was resumed via SendMessage with a computed to-do list (current disk state + the unchanged constraints) rather than respawned fresh, so its already-loaded PRD/SCAFFOLD context was preserved and the modules could not diverge from each other. The resumed run completed normally; its summary follows.

Subagent summary (verbatim):

Implementation complete. All 8 route modules written, compiled, and smoke-tested end to end.

## Files (`workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 56 |
| `core.py` | 488 |
| `calc.py` | 349 |
| `domain.py` | 393 |
| `routes/__init__.py` | 20 |
| `routes/meetings.py` | 303 |
| `routes/packets.py` | 162 |
| `routes/minutes.py` | 72 |
| `routes/instruments.py` | 278 |
| `routes/notices.py` | 105 |
| `routes/codification.py` | 280 |
| `routes/records.py` | 244 |
| `routes/retention.py` | 199 |
| **total** | **2960** |

`compileall` passes; `__pycache__` removed.

## Endpoint coverage: 77/77 — exact match

I extracted every `method`/`path` pair from SCAFFOLD §1.5 and diffed it against `app.url_map`: **0 missing, 0 extra**. (SCAFFOLD line 42 states "15 entities / 77 endpoints"; the earlier working note of 78 was off by one.)

## Startup guarantees
- In-memory only — no sqlite/json/pickle/`/tmp`, no `open()` anywhere in the tree.
- Fresh boot shows all 15 dicts at length 0 and the logical clock at the default `2026-08-01T00:00:00Z`. No seeding.
- `start.sh` installs Flask only when the import fails, then `exec python3 app.py` (avoids pip contention across 8 concurrent rounds).

## Smoke test (`PORT=18694`, killed by PID resolved from `ss -ltnp`, never a pattern-kill)

Auth/envelope: `ERR_UNKNOWN_ROLE` 401, `ERR_ROLE_NOT_PERMITTED` 403, `ERR_NOT_RESOURCE_OWNER` 403, `ERR_INVALID_PAGINATION` 422, list `meta` carrying `limit/offset/total_count/has_more` + `response_type: array`.

Meeting spine: venue -> meeting -> packet -> item (packet `item_count` 1, `contains_public_hearing` true) -> post (72 notice hours, deadline `2026-08-17T18:00Z`, compliant) -> convene (PresidingOfficer only) -> tally (`TWO_THIRDS` on base 5 -> required 4).

Cascade 1 (minutes approval, 4 hops): minutes `APPROVED` -> motion `result_official` true -> instrument `ADOPTED_UNOFFICIAL -> ADOPTED` with minted `ORD-2026-007` -> `ORDINANCE_SUMMARY` notice, 1 insertion, deadline adoption+15.

Cascade 2 (publication -> codification, 4 hops): order (12.5 in -> gross 6250 + 2500 affidavit = 8750; 40 in x 2 insertions = 40000) -> `certify-publication`. With no open cycle a `CODE_AMENDMENT` correctly fails the whole request with `ERR_NO_OPEN_SUPPLEMENT_CYCLE` 409 **before any write**; with a cycle open it enrols a `CASCADE`/`PENDING`/`AMEND` submission. Then lock -> decide -> cycle certify set `current_supplement_number` 1 and drove the instrument to `EFFECTIVE`, basis `SUPPLEMENT_CERTIFIED`, `effective_date 2026-09-11` = max(publication+30 rolled, certified_on). Non-code-amendment path gave `PUBLICATION_PLUS_30` -> `2026-09-09`, staying `PUBLISHED` since it postdates the clock.

Records/money: `due_on 2026-08-10` from Monday intake; `ACTUAL_COST` on the PRD's worked example returned exactly **2125**; payment -> `DEPOSIT_HELD` (balance 1125, net cash 1000); `ERR_PAYMENT_EXCEEDS_BALANCE`; waiver of the remainder -> `PAID` (balance 0, cash held); disposition -> close with `closed_on`.

Retention: accession 150 -> eligibility `2025-01-15`; batch propose; self-certify -> `ERR_SEGREGATION_OF_DUTIES` 403; certify by a second officer -> custody 150/100/50; rescind -> 150/150/0 with zero drift.

## One real bug found and fixed

`domain.new_submission` inserted the new row into `db.submissions` *before* calling `supersede_target(...)`, which has no self-exclusion — so a first client submission superseded **itself** to `WITHDRAWN`, and the cycle then refused to lock with `ERR_CYCLE_NOT_OPEN` (no live submissions). Fixed by adding `exclude_id=None` to `supersede_target` and passing `sub["id"]` from `new_submission` (mirroring what `conflict_target` already did). Verified: lock now returns `LOCKED` with `client_submission_count` 1.

Minor hardening along the way: `waiver_reason` is stored as `_waiver_reason` so it stays out of the serialised entity (it is not a declared `PublicRecordsRequest` field), and `certify` on a destruction batch no longer persists a recomputed `blocking_request_id` on the failure path.

## Step 5: Generate unit tests — 2026-09-04T11:23:00.000Z

Orchestrator placement check: `test_helpers/` and `test_suite/` are both at the task root; `find workspace -maxdepth 2` shows no stray copy of either under `workspace/`, which holds only `INSTRUCTION.md`, `PRD.md` and `implementation/`. No `mv` was needed.

Subagent summary (verbatim):

Stage 2 is complete. The final file, `test_18`, closes out queue B.

## Output

**`test_helpers/`** (9 files, 3,260 lines)

| file | lines |
|---|---|
| `__init__.py` | 161 |
| `api_client.py` | 569 |
| `api_errors.py` | 203 |
| `assertions.py` | 346 |
| `constants.py` | 321 |
| `factories.py` | 472 |
| `fixtures.py` | 1022 |
| `test_users.py` | 109 |
| `types.py` | 57 |

**`test_suite/`** (conftest + 18 test modules, 5,515 lines, **122 tests**)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 93 | — |
| `test_01_fee_schedule_and_effective_date_variants.py` | 210 | 6 |
| `test_02_notice_invoice_and_vote_formulas.py` | 244 | 8 |
| `test_03_state_machine_loops_and_forks.py` | 353 | 7 |
| `test_04_officialization_and_codification_cascades.py` | 178 | 5 |
| `test_05_competing_validation_priorities.py` | 288 | 8 |
| `test_06_inclusive_boundaries.py` | 259 | 6 |
| `test_07_gates_held_by_another_entity.py` | 290 | 6 |
| `test_08_occupation_windows_and_abutment.py` | 186 | 4 |
| `test_09_compensating_reversals.py` | 171 | 4 |
| `test_10_resource_shape_and_defaults.py` | 397 | 12 |
| `test_11_declared_transitions_and_cascades.py` | 458 | 11 |
| `test_12_declared_formulas_and_anchors.py` | 412 | 8 |
| `test_13_declared_input_rules.py` | 270 | 8 |
| `test_14_declared_endpoint_behaviour.py` | 280 | 6 |
| `test_15_error_catalogue_reachability.py` | 319 | 6 |
| `test_16_error_catalogue_second_half.py` | 444 | 6 |
| `test_17_role_boundaries_and_segregation.py` | 242 | 5 |
| `test_18_stale_versions_and_immediate_consistency.py` | 421 | 6 |

## Design-index coverage

- **Queue A (§1.8 difficulty): 24 of 24 live instances translated**, 54 tests — every instance carries 2 or 3 tests (minimum 2 satisfied). No stubs exist in the difficulty design.
- **Queue B (§1.9 corner): 68 of 68 live instances translated**, 68 tests, exactly one test per instance.
- Machine-verified: every `Design:` tag resolves to a real live instance in the correct yaml; no tag points at a stub, no instance is untagged, no test is dual-tagged, and every docstring ends with exactly one `Design:` line.
- The 10 `excluded_because:` corner stubs were correctly **not** translated: 3 in `calculations`, 3 in `state_machines`, 2 in `validations`, 2 in `cross_cutting_complexity_layers`.

## Instances SKIPPED by the PRD filter

**None.** Every non-stub instance in both indices survived the two-condition filter and was translated. Two instances required PRD-clean substitutions rather than a skip, both in corner `rbac/the_editor_who_resolved_the_conflict_cannot_certify_that_supplement_cycle`:
- the design's `action: "AMEND"` against a title with an empty `section_refs` was filed as `ADD`, because PRD §3.7's four enumerated filing gates name no error for an AMEND on an absent section (the prose statement carries no code, so the refusal is not uniquely derivable);
- the design's second instrument was left as `CODE_AMENDMENT` rather than `ZONING`, because PRD §3.5 line 218 forbids `code_title_id`/`code_section_ref` on any non-`CODE_AMENDMENT` ordinance, making the design's setup unbuildable; the conflict was settled by `MANUAL_OVERRIDE`, which preserves the instance's distinguishing aspect (the resolver stamped on a child submission cannot certify the parent cycle).

## Verification run

- `python3 -m py_compile` clean on all 19 suite files.
- `pytest --collect-only`: **122 tests collected**, zero collection errors.
- Citation check (C1-C4): every quoted span in every docstring survives a literal grep of whitespace-normalised `workspace/PRD.md` — `issues: 0`.
- Every `f.`, `fx.`, `a.` and `api_client.` symbol referenced by `test_18` resolves to a real definition in `test_helpers/` (AST cross-check).
- No scaffold references in emitted code or docstrings apart from the mandated `Design:` tags.
- Placement confirmed: `test_helpers/` and `test_suite/` sit at the task root; `workspace/` holds only `INSTRUCTION.md`, `PRD.md` and `implementation/` — nothing was written there and no stray copies exist. `__pycache__` directories from the compile checks were removed.

`test_18` covers the three 412 concurrency guards (stale meeting, code-title and minutes versions, each refused then accepted after a re-read), the version column as a counter of accepted writes, the packet's re-derived `item_count`/`contains_public_hearing` with the 240-hour mirror at posting, and the cancellation fan-out being complete in the response that reports it.

## Step 7: Run tests and iterate — 2026-09-04T12:35:00.000Z

Orchestrator verification: all 8 `workspace/implementation/results.$i.json` files exist on disk and each independently reads `passed=122, total=122`. Sweep was run under `setsid nohup`; no reaping pattern observed.

Subagent summary (verbatim):

All 8 parallel rounds pass 122/122. Done.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 98/122 in every round, 24 failures, fully deterministic (no flakiness — the same 24 tests failed in all 8 rounds). Sweep 2 after fixes: 122/122 in all 8 rounds.

**Tests deleted:** none. Two assertions were removed under STEP 1c partial-coverage handling (see below); no whole test was dropped.

**Assertions removed for PRD silence (STEP 1a — undeclared endpoint):**
- `test_suite/test_15_error_catalogue_reachability.py::test_a_missing_header_pair_and_an_unrecognised_role_are_both_refused_at_the_door` — trailing `validate_paginated(api_client.list_venues(...))` + `total_count=0` check removed. `GET /clerk/venues` does not appear anywhere in the PRD §4 endpoint table (only `POST /clerk/venues`, `GET /clerk/venues/{venue_id}`, `PUT /clerk/venues/{venue_id}`), so the assertion demanded an endpoint the PRD never declares. The covered assertions (the two 401 refusals, PRD 2.1 verbatim) were kept.
- `test_suite/test_17_role_boundaries_and_segregation.py::test_three_crossings_of_the_peer_role_boundary_are_all_refused_alike` — same `list_venues` assertion removed for the same reason; all three `ERR_ROLE_NOT_PERMITTED` assertions and the "nothing moved" state checks kept.

**Fixes applied to `test_helpers/`:**
- `assertions.py` — added `_as_instant()` / `values_equal()` and routed `assert_fields()` and `assert_meeting_notice_mirror()` through them. This fixed 13 tests failing as `expected notice_deadline_at='2026-09-12T18:00:00Z', got '2026-09-12T18:00:00.000Z'`. PRD 2.5 fixes the three-fractional-digit rendering for exactly `created_at` and `updated_at` ("in the same timestamp format"); `scheduled_start`, `notice_deadline_at`, `posted_at`, `adjourned_at` and `notice_posted_at` are only ever described as ISO 8601 UTC instants with no fractional-digit rule anywhere. Both spellings name the same instant and the PRD does not choose between them, so the helpers now assert the instant (which PRD fixes) rather than its spelling (which it does not). The instant comparison is still exact — a wrong instant still fails.
- `fixtures.py` — `adopted_unofficial_ordinance()` gained `clock_at_vote="2026-09-15T18:00:00Z"` and advances the logical clock to the sitting's own day after `in_session_meeting()` and before the motion is recorded. PRD 3.3 stamps `voted_on` from "the logical clock date" at the tally; the fixture previously tallied at the epoch clock (2026-08-01) while the meeting sat on 2026-09-15, so the precondition contradicted the test's (correct) expectation. `in_session_meeting()` itself was deliberately left at the epoch clock — other passing tests assert `adjourned_at='2026-08-01T00:00:00Z'` off it.

**Fixes applied to `implementation/`:**
- `routes/retention.py::create_accession` — returns 200 instead of 201. PRD §4: "an accession, for instance, returns the affected `RecordSeries` rather than a separate accession record", which places it in the "endpoints that transition or mutate a resource" bucket, and "every other successful operation ... answers HTTP 200". Fixed 7 tests failing as `Expected 200, got 201`.
- `routes/records.py::record_payment` — removed the invented `fee_status in (PAID, WAIVED, REFUNDED) -> ERR_INVALID_REQUEST_STATE` gate. PRD 3.8 declares exactly two gates on a payment (`ERR_FEE_NOT_ASSESSED`, then `ERR_PAYMENT_EXCEEDS_BALANCE`); a settled request is caught by the balance gate.
- `routes/records.py::waive_fee` — removed the matching invented `fee_status not in (ASSESSED, DEPOSIT_HELD) -> ERR_INVALID_REQUEST_STATE` gate; PRD 3.8 declares only `ERR_WAIVER_EXCEEDS_BALANCE`. (This one was latent — the payment gate tripped first in the same test.) The PRD-stated CLOSED/WITHDRAWN gate on `assess-fee` and all disclosure-axis state gates were left intact.

**Final per-round results (quoted from `workspace/implementation/results.$i.json`):**

| round | passed / total |
| --- | --- |
| 1 | 122 / 122 |
| 2 | 122 / 122 |
| 3 | 122 / 122 |
| 4 | 122 / 122 |
| 5 | 122 / 122 |
| 6 | 122 / 122 |
| 7 | 122 / 122 |
| 8 | 122 / 122 |

Zero failures, zero errors, zero skips in the union across all 8 rounds.

## Step 8: Finalize PRD — 2026-09-04T12:50:00.000Z

Step 8 was NOT skipped: Step 7 applied 3 `implementation/` fixes, 2 `test_helpers/` fixes and 2 partial-coverage assertion removals, so the skip condition (zero iterations beyond baseline) did not hold. Orchestrator check: `cmp` confirms `PRD_FINALIZED.md` differs from `PRD.md` (99691 vs 98141 bytes).

Subagent summary (verbatim):

Done. Four edits applied to `PRD_FINALIZED.md`.

## Line counts / delta
- `PRD.md`: 494 lines / 98,141 bytes
- `PRD_FINALIZED.md`: 494 lines / 99,691 bytes (**+0.0% lines**, **+1.58% bytes**; every edit is inline inside an existing paragraph, so no line was added or removed)

## Changes
- **§2.5 Common Resource Properties** — *insert* — the three-fractional-digit ISO 8601 UTC rendering is extended from `created_at`/`updated_at` to **every** instant the service returns, naming `Meeting.scheduled_start`, `scheduled_end`, `notice_posted_at`, `adjourned_at`, `AgendaPacket.posted_at`, `notice_deadline_at` and the clock's `current_utc`, with the explicit example that `...T18:00:00Z` reads back as `...T18:00:00.000Z`; calendar-date fields stay bare `YYYY-MM-DD` — `implementation/core.py:109-119` (`iso_ts`/`iso_date`) and `core.py:146-162` (`serialise` routes *all* `datetime` values through `iso_ts`).
- **§4 Endpoint Definitions, opening paragraph** — *revise* — the accession clause now states it "answers HTTP 200 rather than 201, because the resource in `data` is not one the request brought into existence" — `implementation/routes/retention.py:99-102`.
- **§3.8 payment paragraph** — *insert* — pins that the assessed-fee gate and the balance gate are the **only** gates on a payment: no further `fee_status` precondition and none at all on `fulfillment_status` — `implementation/routes/records.py:234-240`.
- **§3.8 waiver paragraph** — *insert* — pins that the balance gate is the **only** gate on a waiver (not even "a fee must have been assessed") — `implementation/routes/records.py:216-220`.

**No edit** for two Step 7 items, deliberately:
- `GET /clerk/venues` (STEP 1a assertion removals): the implementation has **no such route** — `routes/meetings.py` defines only `POST /clerk/venues`, `GET/PUT /clerk/venues/{venue_id}`; an unrouted path falls to the werkzeug handler in `app.py:26-37`. PRD's omission of the endpoint therefore already matches the impl; adding a table row (or an `ERR_NOT_FOUND` catalogue entry) would invent surface.
- `fixtures.py::adopted_unofficial_ordinance` clock advance: pure fixture bug. `routes/instruments.py:209,217` stamps `voted_on = now_date()`, exactly as PRD 3.3 already states.

## Per-edit pre-edit search log
1. **§2.5 timestamp rendering.** (a) Subject: rendering format of every instant-valued field. (b) Enumerated: `core.py:iso_ts`, `iso_date`, `serialise` (single dispatch on `datetime` -> `iso_ts`, on `date` -> `iso_date`); `_meta` (`api_request_timestamp`); `grep -rn '_at"\]'` across all modules -> `notice_deadline_at` (`domain.py:66`), `posted_at` (`packets.py:134`), `notice_posted_at` (`domain.py:91`, `meetings.py:298`), `adjourned_at` (`meetings.py:263`); `grep -rn 'now_dt()\|parse_datetime\|req_datetime'` -> confirms `scheduled_start`/`scheduled_end` (`meetings.py:155-156`, `_req_dt`) and the clock (`meetings.py:26-27`, returns `iso_ts(db.clock)`) are the only remaining instants; all `*_on`, `voted_on`, `adoption_date`, `effective_date` are `date` objects. (c) Adjustment: added the closing sentence separating date-valued fields from instants so the "every instant" claim cannot be read as forcing a time part onto `eligible_through_on`, `due_on`, `publication_dates` etc.; the enumeration is stated as the concrete list the grep proved exhaustive rather than as an open-ended "such as".
2. **§4 accession status code.** (a) Subject: which POSTs answer 201 vs 200. (b) Enumerated every `return ok(...)` in the impl (`grep '@bp.route\|return ok('` over `routes/*.py`): 201 on `create_venue`, `create_series` (number-series), `create_meeting`, `create_packet`, `create_item`, `create_instrument`, `create_motion`, `create_code_title`, `create_cycle`, `create_submission`, `create_request`, `create_series` (record-series), `create_batch`; 200 on `create_accession` (`retention.py:102`), `open_correction` (`minutes.py:72`), `record_payment` (`records.py:246`), `set_clock` (`meetings.py:27`) and every transition/read. (c) Adjustment: phrased the reason as "the resource in `data` is not one the request brought into existence" rather than "an accession creates nothing", so it also correctly explains the 200s on `POST /minutes/{id}/corrections` and `POST .../payments` — both of which do record something but answer with a pre-existing resource — instead of implying they must be 201.
3. **§3.8 payment gates.** (a) Subject: preconditions on `POST .../payments`. (b) Enumerated: `records.py:record_payment` (237-240), `_settle_fee_status` (35-41), `withdraw_request` (151-167, sets `REFUNDED`/`WAIVED` and zeroes the balance), `close_request` (170-185, requires balance 0), `assess_fee` (189-206, which *does* carry the CLOSED/WITHDRAWN gate), `calc.records_request_fee_ledger`. (c) Adjustment: scoped the "no state gate" claim to the payment endpoint only (never to "money-axis operations"), so the PRD-stated CLOSED/WITHDRAWN gate on `assess-fee` is untouched; and wrote "any amount a settled ... request cannot absorb is refused by the balance gate" rather than "a payment against a settled request is refused", because an `amount_cents` of 0 passes both gates in the impl.
4. **§3.8 waiver gate.** (a) Subject: preconditions on `POST .../waive-fee`. (b) Enumerated: `records.py:waive_fee` (209-225), `_settle_fee_status` (35-41), the `fee_status` outcome table already in PRD §3.8, `withdraw_request` (159-166), `close_request` (177-178), and §3.9's `REQUEST_CLOSURE` anchor path (`domain.recompute_series_eligibility`) to confirm a waiver touches no retention path. (c) Adjustment: added "not even that a fee has been assessed at all" because the impl imposes no `NOT_ASSESSED` check here (unlike payment), and mirrored the "amount the current balance cannot absorb" phrasing so a zero-value waiver — which the impl accepts and which then reads `WAIVED` under the PRD's existing balance-0/no-cash rule — is not contradicted.

## Step 9: Complete PRD — 2026-09-04T13:55:00.000Z

Orchestrator design decision (recorded per the AUTONOMY clause): Step 9 was run as THREE SEQUENTIAL module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`, not as a single subagent. A single agent cannot hold a 3000-line implementation plus a 494-line PRD and still do an exhaustive behaviour-by-behaviour walk; the known failure mode is that it emits a byte-identical PRD_COMPLETED.md, i.e. the scan never actually ran. Partition used:
  - Pass 1 — `app.py`, `core.py`, `calc.py`, `domain.py` (shared envelope, RBAC, pagination, serialisation, all 12 calculations, cascade/mirror helpers). Pass 1 alone performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 were explicitly forbidden from re-copying, which would have destroyed prior edits.
  - Pass 2 — `routes/meetings.py`, `routes/packets.py`, `routes/minutes.py`, `routes/instruments.py`.
  - Pass 3 — `routes/notices.py`, `routes/codification.py`, `routes/records.py`, `routes/retention.py`.
Each pass was told which slices the others owned, so no behaviour was double-pinned and none was orphaned.

Orchestrator verification: `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to either `PRD_FINALIZED.md` or `PRD.md`. Sizes: PRD.md 494 lines/98141 chars -> PRD_FINALIZED.md 494/99691 -> PRD_COMPLETED.md 497/116159 (+16468 chars over PRD_FINALIZED, +18.5%). 5 `##` top-level sections intact; file ends on the §5 catalogue's last row (`| ERR_INTERNAL | 500 |`), a genuine section boundary. Total across the three passes: 68 edits (57 ambiguity-pins, 12 mismatch-revisions, 1 catalogue row pair). All 8 `results.$i.json` still read 122/122.

### Pass 1 summary (verbatim)

Pass 1 complete.

**Setup confirmed:** `cp PRD_FINALIZED.md PRD_COMPLETED.md` was performed as the first action (PRD_FINALIZED.md verified present via `ls`). All subsequent work was surgical `Edit` calls on PRD_COMPLETED.md only — no `Write`.

**File metrics:** PRD_FINALIZED.md = 494 lines / 99,691 chars; PRD_COMPLETED.md after pass 1 = 497 lines / 105,306 chars (+3 lines, +5,615 chars). Diff touches 20 existing lines plus 3 inserted lines (1 bullet in 2.2, 2 catalogue rows), all inside my slice's sections.

**Counts:** 17 ambiguity-pins, 5 mismatch-revisions.

**Changes**
- §2.1 — insert — ambiguity — an `X-User-ID`/`X-User-Role` header present but empty counts as absent for `ERR_MISSING_AUTH_HEADERS` — core.py:247-250
- §2.2 success bullets — insert — ambiguity — `api_request_id` is `req_` + twenty uppercase hex characters — core.py:201
- §2.2 success bullets — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not host time — core.py:202
- §2.2 error bullets — insert — ambiguity — framework-level rejections use the same envelope: unrouted path -> `ERR_NOT_FOUND` 404; malformed / method-not-allowed / unsupported media type -> `ERR_INVALID_REQUEST` at 400, 405 or 415 rather than 422; unexpected fault -> `ERR_INTERNAL` 500 — app.py:26-46
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` is `ERR_INVALID_PAGINATION`; an empty-string value falls back to the default — core.py:279-290
- §2.3 — insert — ambiguity — equal `created_at` is tie-broken by server store order, making the listing order total — core.py:194-195
- §2.3 — insert — ambiguity — listing filters are exact equality and an empty-string filter is treated as absent — core.py:299-318
- §2.5 — insert — ambiguity — datetime input grammar (`T` or space, optional seconds, optional fraction, `Z`/numeric offset/no designator; naive read as UTC, offsets converted) and date input must be exactly `YYYY-MM-DD` — core.py:105,122-143
- §2.5 — revise — mismatch — `version` advances by exactly 1 **per request**, not per field write, so a cascade writing one record twice still moves it by 1 — core.py:179-191
- §2.6 — insert — ambiguity — a path matches with or without a trailing slash — app.py:17
- §2.6 — insert — ambiguity — a body-borne identifier present but not a string is reported with that entity's not-found code, not as a shape failure — core.py:474-481
- §2.6 — insert — ambiguity — explicit `null` is treated as absent; non-object or unparseable body is `ERR_INVALID_REQUEST` while an absent/empty body is an empty object; integer fields reject booleans and fractional numbers; strings are stored untrimmed though whitespace-only counts as empty — core.py:264-272,322-373
- §2.9 — insert — ambiguity — `column_inches` accepts a JSON number or a decimal string and reads back as a JSON number — core.py:416-439,160-161
- §2.10 — revise — mismatch — a recomputation of the mirrored notice fields, cycle counters or series eligibility date that changes nothing does **not** stamp `updated_at`/`version` — domain.py:88-95,204-209,359-364
- §3.4 — insert — ambiguity — the officialization cascade pre-simulates every hop-3 mint (including consecutive draws on one series) before hop 1 writes, so a doomed cascade leaves the minutes, motions and instruments — and the heading tally — untouched — domain.py:285-298,391-393
- §3.5 — insert — ambiguity — under `SUPPLEMENT_CERTIFIED`, a certified cycle with no completed publication yields `certified_on` alone — calc.py:128-131
- §3.6 — revise — ambiguity — a new notice also starts with `gross_cost_cents`, `discount_pct` and `invoice_total_cents` null — domain.py:110-113
- §3.6 — insert — ambiguity — the no-discount tier records `discount_pct` as `0.0`, not null — calc.py:171-176
- §3.7 — revise — mismatch — supersession applies only to `origin` `CLIENT` filings; a cascade-raised row never retires a pending row and two live rows may hold the same section — domain.py:251-256
- §3.7 — insert — ambiguity — the sequence component is the integer after the final hyphen of `assigned_number`, and an unnumbered instrument ranks below every numbered one — calc.py:266-276
- §5 intro — revise — mismatch — the status column applies to service-raised errors; framework-level `ERR_INVALID_REQUEST` carries 400/405/415 — app.py:32-37
- §5 table — insert — mismatch — added `ERR_NOT_FOUND` (404) and `ERR_INTERNAL` (500), which the catalogue claimed completeness over but omitted — app.py:33,44

One deliberate non-change worth flagging for later passes: `domain.accepted_cycle_of` (domain.py:168-176) picks the most recently created CERTIFIED cycle when an instrument has accepted submissions in more than one; I left this unpinned as unreachable-in-practice rather than add prose. Route-level behaviours noticed while reading shared helpers (e.g. where `precheck_minutes_cascade` and `packet_derived` are invoked, 201-vs-200, per-endpoint enums) were left entirely to passes 2 and 3.

### Pass 2 summary (verbatim)

Verification complete. The file is structurally intact (5 `##` headings, 160 table rows, all sections present).

**No `cp` was run.** All 22 changes were applied with the Edit tool in place on the existing `workspace/PRD_COMPLETED.md`.

| | lines | chars |
|---|---|---|
| before pass 2 | 497 | 105,306 |
| after pass 2 | 497 | 109,985 |

(Line count is unchanged because every change is an in-paragraph insert or revision — no new paragraphs or sections.)

**Counts: 19 ambiguity-pins, 3 mismatch-revisions.**

- §2.4 The Logical Clock — insert — ambiguity — `to_iso8601` is required and `current_utc` is the sole field of `data` — meetings.py:24-27
- §3.1 (venue register) — insert — ambiguity — every field of a venue revision is optional, an omitted field is left as it stands, and the revision stamps the venue whether or not a value actually changed; the overlap arithmetic always reads the venue's *current* `teardown_buffer_minutes` for both sides of the comparison — meetings.py:59-74, 122-141
- §3.1 (occupation) — insert — ambiguity — the overlap check is evaluated before the closed-room check, so a booking that both collides and names a closed room reports `ERR_VENUE_WINDOW_CONFLICT` — meetings.py:160-163
- §3.1 (occupation) — **revise** — **mismatch** — PRD claimed "both checks apply again" on a reschedule; impl re-runs only the overlap check (excluding the moving meeting's own claim) and never re-checks `ERR_VENUE_CLOSED` — meetings.py:222-225
- §3.1 (cancellation) — revise — ambiguity — cancelling from `NOTICED` also clears `required_notice_hours` — meetings.py:298-300
- §3.1 (cancellation) — insert — ambiguity — `cancelled_reason` must be a non-empty string — meetings.py:288
- §3.2 (packet revisions) — insert — ambiguity — supersession leaves the superseded posting's `MEETING_AGENDA` notice untouched; the revision limit is examined after the version check; the operation has no precondition on the meeting's `status` — packets.py:22-30, 16-50
- §3.2 (posting) — insert — ambiguity — a meeting not in `SCHEDULED` is `ERR_INVALID_MEETING_STATE` (409); packet-state -> meeting-state -> empty-packet is the evaluation order; every posting raises a fresh notice so a re-noticed meeting can hold several — packets.py:126-142
- §3.2 (withdrawal) — **revise** — **mismatch** — withdrawal voids *every* live `MEETING_AGENDA` notice (not one), and where the meeting has moved past `NOTICED` its status is left alone while the mirrored fields are still cleared; no meeting-state precondition — packets.py:150-161
- §3.3 (convene) — insert — ambiguity — `present_member_count` is a required non-negative integer — meetings.py:243
- §3.3 (motion register) — insert — ambiguity — `agenda_item_id` need only exist and is not cross-checked against the meeting's packets; `tie_break_used` false and `effective_base`/`required_yes` null at creation — instruments.py:159, 171-175
- §3.3 (tallying) — insert — ambiguity — the motion's own state is examined before its meeting's; the four counts are required non-negative integers — instruments.py:244-253
- §3.3 (consequences) — revise — ambiguity — "failing" means `FAILED` or `TIE_BROKEN_FAILED`; a failing `RESOLUTION_ADOPTION` leaves the resolution in `INTRODUCED`; a failing `MINUTES_APPROVAL` leaves the record in `SUBMITTED` — instruments.py:199-230
- §3.3 (consequences) — insert — ambiguity — every consequence is conditional on the target already being in the named state; otherwise the tally still records and answers 200 and the hop is silently skipped — instruments.py:206-236
- §3.3 (adjournment) — **revise** — **mismatch** — PRD claimed the un-tallied-motion sweep also runs on cancellation; `cancel_meeting` runs no sweep (and cannot need one) — meetings.py:283-303
- §3.4 (drafting/submission) — insert — ambiguity — `text_body` is required on a write and may be empty; a non-`ADJOURNED` parent is `ERR_INVALID_MEETING_STATE`; an empty narrative at submission is `ERR_INVALID_MINUTES_STATE`, checked with the record's state and before the meeting; "empty" means literally `""`, so whitespace counts as a narrative — minutes.py:37, 49-53
- §3.4 (corrections) — insert — ambiguity — `corrected_text_body` must be non-empty — minutes.py:64
- §3.5 (number series) — insert — ambiguity — `series_year` >= 1; `prefix` need only be non-empty and is not constrained to letters; `next_sequence` ranges 1-999 — meetings.py:82-86
- §3.5 (number series) — insert — ambiguity — closing a series that is not `OPEN` is `ERR_NUMBER_SERIES_CLOSED` (409) — meetings.py:114-115
- §3.5 (introduction) — insert — ambiguity — `code_section_ref`'s dotted spelling is not validated, only non-emptiness — instruments.py:35
- §3.5 (introduction) — insert — ambiguity — the closed-series check precedes the class/year comparison — instruments.py:48-52
- §3.5 (readings) — insert — ambiguity — a resolution, or an ordinance not in `INTRODUCED`, is `ERR_INVALID_INSTRUMENT_STATE` (409), evaluated before the meeting-state check — instruments.py:101-105
- §3.5 (veto) — insert — ambiguity — `veto_reason` is required and non-empty — instruments.py:117

Notes on scope discipline: I made no edits to §2.x other than the §2.4 clock sentence (my slice owns that endpoint), left every §3.6-§3.9 passage to pass 3, and left pass 1's shared-layer prose (envelope, RBAC ordering, pagination, `version`-per-request rule, mirror/no-op-recompute rule, cascade all-or-nothing text) untouched — my §3.3 "conditional skip" and §3.2 "no precondition" inserts are consistent with, not contradictory to, 2.10/2.11.

### Pass 3 summary (verbatim)

Pass 3 complete. No `cp` was run at any point — every change was an in-place `Edit` on the existing `workspace/PRD_COMPLETED.md`.

**File size**: 497 lines / 109,985 chars before -> 497 lines / 116,159 chars after (+6,174 chars; all edits were in-paragraph, so the line count is unchanged).

**Counts**: 20 ambiguity-pins, 4 mismatch-revisions (24 changes via 23 Edit calls).

**Changes**
- §3.6 (order inputs) — insert — ambiguity — all four order fields required (`affidavit_required` a required boolean, no default), and `column_inches` accepts more than two decimal places — `routes/notices.py:35-38` (+ `core.req_decimal` called without `max_places`)
- §3.6 (order gates) — insert — ambiguity — the three scheduling rules run in the stated order and after the `DRAFT` state check — `routes/notices.py:40-49`
- §3.6 (certification) — insert — ambiguity — a `publication_completed_on` that isn't the latest ordered date (or a notice with no dates) is `ERR_INVALID_REQUEST` 422, checked after the `ORDERED` state test — `routes/notices.py:70-75`
- §3.7 code titles — insert — ambiguity — `RESERVED` is descriptive only; no operation consults title status — `routes/codification.py:24,53,173`
- §3.7 code titles — revise — **mismatch** — `section_refs` membership is *not* a filing gate (impl never checks it; `ERR_CODE_SECTION_UNKNOWN` is only the instrument/cycle agreement) — `routes/codification.py:200-202`
- §3.7 cycles — insert — ambiguity — `window_close_on` before `window_open_on` -> `ERR_SUPPLEMENT_WINDOW_CONFLICT` 409, before the collision scan — `routes/codification.py:65-66`
- §3.7 submissions — revise — **mismatch** — the three-submission cap is evaluated **before** the window check (PRD had listed window first) — `routes/codification.py:195-199`
- §3.7 submissions — insert — ambiguity — the pending row a filing is about to supersede is discounted from the cap — `routes/codification.py:191-195`
- §3.7 cascade origin — insert — ambiguity — a `CASCADE` submission does not advance the `CodeTitle.version` — `routes/notices.py:103` vs `routes/codification.py:205`
- §3.7 lock — insert — ambiguity — lock needs >=1 non-withdrawn row; both wrong-state and empty-cycle report `ERR_CYCLE_NOT_OPEN` — `routes/codification.py:114-117`
- §3.7 conflict bases — insert — ambiguity — `winning_submission_id` presence is shape-pass, but the "names one of the pair" test runs after the state checks — `routes/codification.py:253,264-267`
- §3.7 certify effects — insert — ambiguity — accepted rows applied in creation order; `ADD` of an existing ref duplicates it, `REPEAL` of an absent ref is a no-op — `routes/codification.py:151-158`
- §3.7 certify effects — insert — ambiguity — `PUBLISHED -> EFFECTIVE` here ignores the effective date; a non-`PUBLISHED` accepted instrument is only recomputed and stamped — `routes/codification.py:161-168`
- §2.8 — revise — **mismatch** — segregation of duties is evaluated *after* the target's state check (and, on a cycle, after the conflict/open-submission checks), not before — `routes/codification.py:134-144`, `routes/retention.py:155-158`
- §3.8 intake — insert — ambiguity — the three intake strings are required and unvalidated in form; no email syntax check — `routes/records.py:49-51`
- §3.8 intake — insert — ambiguity — `fee_schedule_variant`, `closed_on`, `denial_basis` enter null — `routes/records.py:65-74`
- §3.8 exemption review — insert — ambiguity — only the claim count is read/stored; an empty list is accepted and leaves `exemption_count` 0 — `routes/records.py:115-119`
- §3.8 withdrawal — insert — ambiguity — `fee_status` is left exactly as it stood when nothing was assessed or collected, and no `closed_on` is written — `routes/records.py:159-166`
- §3.8 assessment — insert — ambiguity — each line must be an object with three required fields; an empty `fee_lines` assesses 0 and stays `ASSESSED` with a zero balance — `routes/records.py:20-32,195-203`
- §3.8 payment — insert — ambiguity — `amount_cents` is a required non-negative integer; a 0 payment is accepted and restates `fee_status` — `routes/records.py:233`
- §3.8 waiver — insert — ambiguity — `waived_cents` non-negative (0 allowed); `waiver_reason` required but not a field of the resource and absent from its representation — `routes/records.py:214-222` (+ `core.serialise` dropping `_`-prefixed keys)
- §3.9 series — revise — **mismatch** — the series update touches only `legal_hold_status`/`permanent`, ignores every other field, and stamps `version`/`updated_at` unconditionally (even on an empty body) — `routes/retention.py:69-82`
- §3.9 accession — insert — ambiguity — `item_count` need only be non-negative; a 0-item accession still moves the anchor — `routes/retention.py:90`
- §3.9 certify — insert — ambiguity — permanence is re-checked at signature (`ERR_SERIES_PERMANENT_RETENTION`), and the recomputed null `blocking_request_id` overwrites the proposal snapshot — `routes/retention.py:164-165,172`

**Structural integrity check: PASS.** 5 `##` top-level sections present (1 Introduction, 2 Global Specifications, 3 Business Logic, 4 Endpoint Definitions, 5 Error Code Catalogue); §4 endpoint table still 77 rows and §5 error catalogue still 79 rows (both unchanged — no rows added or removed); both table header separators intact.

Notes for the caller: two PRD-internal contradictions were resolved in favour of the implementation — §2.8's claim that segregation of duties precedes the state/aggregate checks (impl puts it after), and §3.7's gate ordering where the submission cap actually precedes the window check (which also brings §3.7 into line with §2.11's stated family order). I deliberately did not touch §2.6's shape-pass list or §2.9's money prose (pass 1 territory); the two behaviours that brushed against them (`column_inches` decimal places, and the deferred `winning_submission_id` membership test) were pinned locally in §3.6/§3.7 instead.

## Pipeline complete — 2026-09-04T13:56:00.000Z

All nine steps done. Final state: 15 entities / 77 endpoints / 122 tests, 8/8 sweep rounds at 122/122, `workspace/PRD_COMPLETED.md` written (497 lines).
