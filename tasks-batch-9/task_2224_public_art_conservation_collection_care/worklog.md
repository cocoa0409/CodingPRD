# Worklog — task_2224_public_art_conservation_collection_care

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2224_public_art_conservation_collection_care/` and `tasks/task_2224_public_art_conservation_collection_care/workspace/` (pre-allocated task name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-01T08:55:09.000Z

All three scaffold artifacts are complete and lint-clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2224_public_art_conservation_collection_care/`)
- `SCAFFOLD.yaml` — §1.0–§1.7 only (top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles; neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**§1.0–§1.7 counts (well above expert calibration)**
- 14 entities, 68 endpoints, 9 state machines, 6 calculations, 42 validations, 62 error codes, 9 roles, 2 OCC concurrency rules
- Profile: compliance_audit / multi_party_negotiation, flat topology, cyclic state machines, segregation_of_duties role model, layers = optimistic_concurrency + cascading_side_effects + dual_variant_calculation + scheduled_actions, immediate consistency
- Hardening highlights: two entities with parallel state dimensions (Artwork custody vs conservation; DamageIncident damage vs claim), three multi-hop cascades (CASCADE A 5 hops on survey finalization, CASCADE B 4 hops on deaccession execution, CASCADE C 3 hops on proposal approval), two dual-variant calculations (treatment_priority_score, claim_settlement_cents), a deliberately pinned circular endowment draw (tier keyed on gross, fee withheld after), half-open vs closed interval conflict rules, and a logical clock pinned at 2026-08-01T00:00:00Z

**Design-file instance counts**
- §1.8: 19 instances across the 9 difficulty rules (2/2/2/2/3/2/2/2/2)
- §1.9: 60 instances across the 9 claim-extraction sections — entities 7, state_machines 15, calculations 10, validations 8, endpoints 3, errors 7, rbac 4, complexity_layers 5, consistency_model 1; 15 of those are `excluded_because` stubs deferring to named §1.8 instances, so 45 carry full `test_recipe`s
- All 62 error codes are triggerable somewhere in §1.8/§1.9; every instance name is unique across the union of both files

**Verification**
- `scaffold_lint.py` on the task dir: 68 endpoints / 14 entities / 19 §1.8 instances / 45 §1.9 instances / 898 calls scanned → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`
- Every asserted literal (condition indices, priority scores, proposal estimates, pool draw/fee/available balances, ACV depreciation and settlements, all deadline dates) was recomputed with Decimal/ROUND_HALF_UP and date arithmetic; setup chains were replayed call-by-call for state/priority preconditions (e.g. proposal creation requires a FINALIZED survey, one proposal per assessment, fresh OCC tokens re-read after each version bump, quorum reached only on the 5th non-RECUSE ballot).

## Step 3: Copy shared files — 2026-09-01T08:55:09.000Z

Copied `INSTRUCTION.md` → `tasks/task_2224_public_art_conservation_collection_care/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T09:10:42.000Z

PRD generated and all three Hard Contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2224_public_art_conservation_collection_care/workspace/PRD.md` — **511 lines**

**Sections**

- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (pasted verbatim) · 2.3 Pagination · 2.4 Register Reads and Reverse Lookups · 2.5 Common Record Properties · 2.6 The Logical Conservation Clock · 2.7 Two Independent Status Dimensions · 2.8 Order of Evaluation (the 42-step pipeline) · 2.9 Cascade Discipline (A/B/C) · 2.10 Precision, Rounding and Money · 2.11 Guarding Against Stale Reads
- §3 Business Logic & Workflows — 3.1 Building the Register · 3.2 Condition Surveys, Photographic Documentation and the Condition Index · 3.3 Routine Material Care: Protocols, Windows and the Graffiti Response Clock · 3.4 Engaging a Conservator: Vendors, Proposals and the Estimate · 3.5 Approval Gates and Treatment Execution · 3.6 Moral Rights: Consultations and Statutory Notices · 3.7 Custody Moves and Relocation · 3.8 Deaccession: Criteria, Public Comment, Ballots and Disposition · 3.9 Priority Ranking and the Cycle Checkpoint · 3.10 Funding: Endowment Draws, Set-Asides and Reservations · 3.11 Damage Response and Insurance Recovery
- §4 Endpoint Definitions — 68 rows, exact one-to-one match with the scaffold (no missing, no invented)
- §5 Error Code Catalogue — 62 rows, all IDs present with statuses matching the scaffold exactly

**Coverage audit**

```
Field coverage check:
- entities[].fields: 143 required, 143 present, 0 missing
- endpoints[].request_body: 114 required, 114 present, 0 missing
- endpoints[].query_params: 36 required, 36 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 42 checked, 42 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 61 checked, 61 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed, 0 missing
- validations[] conditions: 42 checked, 42 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 114 checked, 114 expressed, 0 missing
- entities[].fields[] structured content: 143 checked, 143 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 875
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notes**

- Two repairs were made on the second pass: §2.8 step 5 now names every body-FK not-found code explicitly rather than deferring to step 3, and §3.6 now states the notice-consumption transition with both origin statuses (`ACKNOWLEDGED → CONSUMED` and `WAIT_ELAPSED → CONSUMED`) instead of only the destination.
- All internal constant *names* (`GRAFFITI_SLA_HOURS`, `OVERHEAD_PCT`, `CONTINGENCY_PCT`, `MOBILIZATION_FLAT_CENTS`, the tier/limit/deductible constants, `MIN_ASSESSMENT_PHOTOS`, `MAX_REVISION_ROUNDS`, `QUORUM_MIN_VOTES`, `APPROVE_RATIO_MIN`, `CONSERVATOR_BUFFER_HOURS`, `TREATMENT_TRIGGER_INDEX`) are translated to prose with their literal values rather than reproduced as identifiers, per the no-pseudocode rule; a spot-check confirmed all 68 numeric literals from the calculation blocks appear in the text.
- Deliberate contrasts preserved in prose: site work windows are closed intervals (touching endpoints collide) versus conservator engagement windows half-open and padded 48 hours both sides; contingency computed on subtotal-plus-overhead; endowment tier keyed to the gross pre-fee draw; round-per-line-then-sum declared normative; `sla_breached` strictly greater-than so equality is compliant; `decision_ratio` exactly 0 on a zero denominator.
- The two withheld design YAMLs were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T09:53:00.000Z

Generation is complete and audited.

**Files written** — all under `/home/ubuntu/github/CodingPRD/tasks/task_2224_public_art_conservation_collection_care/`

`test_helpers/` (9 files, 2,486 lines): `__init__.py`, `api_client.py` (every `/public-art` endpoint plus `/_clock/set_current_utc`), `api_errors.py` (`ApiErrorId` enum, all 62 ids, registered with the framework's status map), `types.py`, `constants.py`, `factories.py`, `fixtures.py` (composite setup builders, all driven through PRD endpoints), `assertions.py` (entity shape + money-invariant helpers), `test_users.py` (9 roles, plus `make_conservator_vendor_headers` / `make_commission_member_headers` / `make_artist_headers` ownership-scoped factories).

`test_suite/` (`conftest.py` + 16 test files, 7,108 lines, **127 tests**):
- Queue A — difficulty, `test_01`–`test_08`, **48 tests**: survey review loop; custody moves and dual-variant priority scoring; estimate build-up + endowment pool tiers; proposal approval gates; visit windows and starts; deaccession ballots and Cascade B execution; Cascade A finalize + fund-release compensating invariant; ACV vs restoration claim bases.
- Queue B — corner, `test_09`–`test_16`, **79 tests**: entities (10), state machines (10), calculation edges (10), validations (9), endpoints/consistency model (7), refusal paths (16), RBAC and ownership (9), complexity layers/stale reads (8).

**Coverage**: all 19 difficulty instances have ≥2 tests each; all 45 non-stub corner instances have ≥1 test each; each file has ≥5 tests.

**Instances skipped**: none on PRD-derivability grounds. The 15 corner instances carrying `excluded_because:` were deliberately translated to nothing, as specified. Where the design yaml disagreed with the PRD the PRD won — invalid `treatment_scope`/`criteria` enum literals were replaced with PRD enum members, and yaml-claimed HTTP statuses that contradict §5 (e.g. `ERR_WINDOW_IN_PAST` as 409 when §5 maps it to 422) were dropped in favour of asserting the `error_id` and letting the registered status map cross-check. A handful of individual sub-assertions the PRD did not uniquely derive were also dropped rather than weakened.

**Verification performed** (throwaway scripts in `/tmp`, no report files): every `PRD §x.y: "..."` citation greps verbatim into `workspace/PRD.md` (0 bad citations across all 16 files, markdown bold markers included); tests == `Design:` tags in every file, exactly one tag per test, always the docstring's last line, none on helpers, 0 unresolved or stub-pointing tags; no `scaffold`/`xfail`/`pytest.mark.skip`/yaml references anywhere; `pytest --collect-only` collects 127 tests with no import errors; an AST sweep confirms every `api.*`, `fixtures.*`, `factories.*`, `assertions.*`, `constants.*`, `ApiErrorId.*` reference resolves (0 missing).

One caveat worth relaying: the suite was validated by static audit and collection only — the API server implementation does not exist yet, so no test has been executed against a live implementation.

**Orchestrator note:** Steps 5 and 6 ran sequentially rather than in one concurrent assistant message (orchestrator slip). The physical-isolation guarantee the concurrency provides was replaced by an explicit hard read-ban in the Step 6 prompt forbidding any read/ls/glob/grep of `test_suite/` and `test_helpers/`; the Step 6 subagent confirmed on exit that it never touched either directory.

## Step 6: Generate implementation — 2026-09-01T10:24:04.000Z

Implementation complete.

## Files written
All in `/home/ubuntu/github/CodingPRD/tasks/task_2224_public_art_conservation_collection_care/workspace/implementation/` (16 files, no subpackages):

- `start.sh` — `set -euo pipefail`, `cd "$(dirname "$0")"`, pip-installs only if `import flask` fails (keeps per-test reboots fast and avoids pip contention), then `exec python3 app.py`
- `requirements.txt` — `Flask>=2.2`
- `app.py` — app factory, blueprint registration, `before_request`/`teardown_request` global RLock, error handlers (`ApiError`, 404 → `ERR_NOT_FOUND`, 405 → `ERR_METHOD_NOT_ALLOWED`, other `HTTPException` → `ERR_INVALID_REQUEST`, catch-all → `ERR_INTERNAL`); listens on `0.0.0.0:$PORT`, default 10000 per INSTRUCTION.md
- Infrastructure: `db.py` (in-memory `Store` of 14 dicts + logical clock, id/timestamp/version minting), `errors.py` (all 66 catalogue ids with PRD §5 statuses, verified row by row), `response.py` (meta envelope, listing/paging meta), `middleware.py` (9 roles, `X-User-ID`/`X-User-Role`, ownership), `validate.py` (strict input specs, unknown-field rejection, filters, paging), `calc.py` (all numeric rules with `Decimal`/`ROUND_HALF_UP`), `services.py` (resolvers, roll-ups, money helpers, Cascades A/B/C)
- Routes: `routes_registry.py` (15), `routes_survey.py` (11), `routes_treatment.py` (9), `routes_rights.py` (14), `routes_money.py` (13), `routes_ops.py` (2)

## Endpoint count
68/68 — matches both the PRD §4 table and the SCAFFOLD `endpoints:` list; `app.url_map` enumerates exactly 68 non-static rules.

## Notable design decisions
- **Storage**: pure Python dicts, zero seeding. Verified at import time that every store is empty and the clock is exactly `2026-08-01T00:00:00Z` on a fresh process; nothing reads the wall clock, all timestamps derive from the logical clock moved only by `POST /_clock/set_current_utc`.
- **One request at a time** via an RLock held for the whole request, so a multi-hop cascade is never observed halfway.
- **Exactly one version bump per record per request**, tracked in a flask-`g` touched set; roll-up recomputes touch only on a real value change.
- **Gate ordering** for every multi-guard operation was diffed against the SCAFFOLD `business_rules` priorities 3–42 and PRD §2.8's 42-step global order — e.g. proposal draft (FK → OCC → consent → eligibility → exclusivity → funding), deaccession execute (state → in-collection → recognized stature → moral-rights notice → disposition target), file-claim (claim dimension checked before damage dimension), allocation reserve (FK → OCC → link mismatch → funds).
- **Arithmetic**: `Decimal` with `ROUND_HALF_UP` throughout; per-line rounding then summing for estimates; ACV depreciation rounded once before the extent multiplier; endowment tier pinned to the gross pre-fee draw; condition index 1 dp floored at 0; priority score rounded once to 2 dp.
- **Interval contrast** preserved: site work windows are closed (touching endpoints collide → `ERR_SITE_WORK_CAPACITY_CONFLICT`); conservator engagement windows are half-open with 48h padding on both sides.
- **Undeclared-error fallbacks** chosen defensibly: empty `line_items` on submit → `ERR_PROPOSAL_INVALID_STATE` (409); an IN_PROGRESS visit blocking start-execution → `ERR_ARTWORK_CUSTODY_INVALID` (409); pagination violations → `ERR_INVALID_REQUEST` (400).

## Boot confirmation
`bash start.sh` boots clean from a fresh process, repeatedly: two consecutive launches on the same port each answered `GET /public-art/sites` with `200` and an empty `data` array, with `api_request_timestamp` back at `2026-08-01T00:00:00.000Z` — confirming no state or clock drift survives a restart. Auth/routing spot checks return 401 (no headers), 403 (wrong role on a funding read), 404 (unknown route). A 79-assertion end-to-end smoke test covering all three cascades, the funding/insurance arithmetic, the deaccession quorum tally, moral-rights gating, and the run-cycle checkpoint passes in full (e.g. condition index 30.3 → PRIORITY band, priority score 135.92, pool admin fee 129,375 / authorized 5,620,625, estimate total 1,267,598, quorum ratio 0.8).

Constraints honored: `test_suite/`, `test_helpers/`, the two `SCAFFOLD_*_DESIGN.yaml` files, and all sibling task directories were never read, listed, globbed, or grepped; the build came solely from `PRD.md`, `SCAFFOLD.yaml`, and `INSTRUCTION.md`.

## Step 7: Run tests and iterate — 2026-09-01T10:41:15.000Z

All green. Final state: 8/8 parallel rounds at 127/127.

## Summary

**Iterations run:** 2 (sweep 1 → diagnose/fix → sweep 2 clean).

**Sweep 1 result:** 125/127 in all 8 rounds; the same 2 tests failed in every round (deterministic, no flakiness observed anywhere in the suite).

**Tests deleted:** none. Both failures survived STEP 1 (PRD verbatim-covers and uniquely determines the asserted rule), so both were resolved under STEP 2 / STEP 3.

**Fixes applied to `test_helpers/`:** none. The one test bug lived in the test function itself, not in a shared fixture.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2224_public_art_conservation_collection_care/test_suite/test_12_business_rule_validation.py`, `test_duplicate_business_code_is_refused_on_every_entity_that_carries_one` — STEP 2 test bug: the test used the site row as returned by `setup_register` (version 1) as the "unchanged" baseline, but PRD §2.5 ("when a computed roll-up such as `artwork_count`, `installed_units_used` … is recomputed, the affected record's `updated_at` is refreshed and its `version` is incremented") plus §3.1 ("raises the site's `installed_units_used` by the work's `footprint_units`") mean accessioning the register's own artwork legitimately bumps the site to version 2. The stale snapshot, not the server, was wrong. Fixed by re-reading the site (`site_before = read_site(...)`) immediately before the four refused duplicate-code requests, so the baseline is the state the refusals are actually being measured against. The assertion itself was not weakened — it still demands an exact zero version delta.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2224_public_art_conservation_collection_care/workspace/implementation/routes_money.py`, `create_incident()` — added the missing `svc.require_in_collection(artwork)` call. Reporting damage against a `DEACCESSIONED` work returned 201 instead of `ERR_ARTWORK_DEACCESSIONED`, contradicting PRD §2.8 step 12: "The referenced artwork is not already out of the collection — `ERR_ARTWORK_DEACCESSIONED`. This guards every write that references an artwork." The guard is placed after body-FK resolution (§2.8 step 5) and before record creation, matching the specified evaluation order. Cross-checked the other 13 artwork-referencing writes — all already carried the guard; this endpoint was the sole omission.

No assertions were relaxed, no skips/xfails added, no PRD-required check removed, and no data is seeded at startup (storage remains in-memory dicts only).

**Orchestrator verification note:** the Step 7 subagent left no `results.*.json` on disk, so the orchestrator re-ran the full 8-round parallel sweep itself (after two malformed `--start-command` invocations that failed to locate `start.sh` and were discarded). The confirmed final sweep, with `--start-command "cd .../workspace/implementation && bash start.sh"`, wrote `results.{1..8}.json` into `workspace/implementation/`: all 8 rounds `127/127 passed, 0 failed, 0 errors, 0 skipped` (~163 s per round).

## Step 8: Finalize PRD — 2026-09-01T10:47:18.000Z

`PRD_FINALIZED.md` is written. Note: `test_suite/` and `test_helpers/` do not exist in this workspace, so I aligned purely against `implementation/` and used the `<step_7_diff>` narrative to scope the edits.

## Line counts
- `PRD.md`: 511 lines / 85,513 bytes
- `PRD_FINALIZED.md`: 513 lines / 87,140 bytes
- Δ = +2 lines (**+0.39%** lines, +1.9% bytes); 1 line revised in place, 2 lines inserted. No sections added, no prose deleted.

## Changes

- **§2.5 Common Record Properties — insert — pins the two `version`-counter qualifications the implementation enforces: (a) a roll-up recomputation that produces the value already stored is *not* a mutation (no `updated_at`/`version` change), (b) `version` rises by at most one per request no matter how many writes/hops land on the record, and a record created by the request stays at `version` 1 — `implementation/db.py:122-146` (`create_record`, `touch` with the per-request `_touched_set()`), `implementation/services.py:109-213` (every `recompute_*` gated on `!=`).**
- **§2.8 Order of Evaluation, step 12 — revise — replaces the universal "This guards every write that references an artwork." with the exact set the implementation guards (all 8 writes naming an `artwork_id` in path/body, plus the survey/visit/proposal/case transitions that act on the work, with the first-pass carve-outs cross-referenced) and names the writes that do not consult it — `implementation/routes_money.py:177` (the Step 7 fix) plus the other 17 `require_in_collection` callsites.**

## Per-edit pre-edit search log

### Edit 1 — §2.5 version semantics
- **(a) Subject:** what refreshes `updated_at` / increments `version`, i.e. the exact §2.5 sentence the Step 7 test fix cited to justify the site row moving to `version` 2 on accession.
- **(b) Paths enumerated:** `grep -n '"version"' *.py` → only `db.py:128` (`create_record`, sets 1) and `db.py:146` (`touch`, +1); nothing else ever writes `version`. Read `db.py:113-147` (`_touched_set()` keyed on flask `g`, so dedupe is per request; `create_record` pre-registers the new id) and `app.py:36-45` (one request at a time under `db.lock`, fresh `g` per request). Read all 7 roll-ups in `services.py` — `recompute_artist_count` (109), `recompute_site_units` (118), `recompute_open_notice_count` (130), `recompute_engagement_count` (144), `recompute_maintenance_ytd` (157), `recompute_pool` (178), `recompute_ranks` (196) — every one touches only when the recomputed value differs. Read the multi-touch-in-one-request sites: `cascade_a` (artwork touched at hop 2 then again by `recompute_ranks`), `cascade_b` (artwork touched at hop 1 then by `recompute_open_notice_count`; one pool touched once even when several allocations release), `cascade_c`, `release_allocation`/`advance_allocations` (alloc + pool), `routes_survey.py:319-323` (`complete_visit`: artwork dates then `recompute_maintenance_ytd`), `routes_treatment.py:286-291` and `311-318` (artwork + `recompute_ranks`), `routes_money.py:297-303` (`resolve_claim`: `touch(pool)` then `recompute_pool`), `routes_registry.py:183-184` (the Step 7 accession site), `routes_treatment.py:83` (`touch(artwork)` on draft, which drives the `expected_artwork_version` check). Also checked the 55 `touch(...)` callsites for any unconditional-vs-conditional asymmetry.
- **(c) Wording adjustment:** the "unchanged value is not a mutation" clause was deliberately **scoped to computed/rolled-up values only**, because direct field writes are unconditional — e.g. `complete_visit` rewrites `last_maintenance_completed_on` and touches even if the date is identical, and `suspend_conservator`/`respond_consultation` touch on plain assignment. A generic "writing the same value is not a mutation" would have mis-described those paths. I also named `available_cents` and `treatment_priority_rank` explicitly, since the existing §2.5 example list ("such as `artwork_count`, `installed_units_used` …") does not mention them yet both are change-gated in `recompute_pool`/`recompute_ranks`. The per-request clause was phrased as "at most one" (a ceiling, not a schedule) so it cannot contradict §2.9's per-hop increment sentence, which stays verbatim.

### Edit 2 — §2.8 step 12 guard coverage
- **(a) Subject:** which writes evaluate `ERR_ARTWORK_DEACCESSIONED` (the Step 7 implementation fix added the missing call in `create_incident`).
- **(b) Paths enumerated:** `services.py:93-96` (`require_in_collection`; `TERMINAL_CUSTODY = ("DEACCESSIONED", "DESTROYED")`, so `DESTROYED` also trips it — consistent with §2.7's "out of the collection", left unchanged). `grep -rn require_in_collection` → 18 callsites: `routes_registry.py:226` (relocate), `routes_survey.py:51` (open survey), `:121` (submit, `if first_pass`), `:153` (finalize), `:194` (schedule visit), `:269` (start visit), `:291` (complete visit), `routes_treatment.py:49` (draft, after the OCC check), `:149` (submit, `if status == DRAFT`), `:237` (approve), `:274` (start-execution), `:306` (complete), `routes_rights.py:54` (consultation), `:126` (notice), `:192` (open case), `:240` (advance, inside the `INITIATED` branch only), `:306` (execute), `routes_money.py:177` (report damage — the fix). Then swept every remaining POST handler to confirm the negative list: `attach_photo`, `request_assessment_revision`, `append_line_item`, `request_proposal_revision`, `reject_proposal`, `respond_consultation`, `acknowledge_notice`, `cast_ballot`, `triage_incident`, `file_claim`, `resolve_claim`, `create_allocation`, `release_allocation`, `suspend_conservator` — none call it. Also grepped `"artwork_id": field(` (7 body-carrying creates, all guarded) and the URL rules (`<artwork_id>` appears on a write only in `relocate`), so the "names an `artwork_id` in its path or its body" universal is exactly true.
- **(c) Wording adjustment:** dropped the original universal, which over-claimed against `respond_consultation`, `acknowledge_notice`, `cast_ballot`, `triage_incident`, `file_claim`, `resolve_claim`, `append_line_item`, `attach_photo`, the two revision requests, `reject_proposal` and both funding writes. The three partial guards are marked "first pass/first advance only" with cross-references to §3.2/§3.4/§3.8 rather than restated, so no existing prose had to change; the ordering claim ("before any material, funding or scheduling rule") in the following paragraph stays verbatim and still matches `approve_proposal`, `start_visit`, `create_proposal` and `execute_case`.

## Step 9: Complete PRD — 2026-09-01T10:58:37.000Z

Verified: 35 lines changed (34 revised in place, 1 bullet inserted), no new sections, structure intact.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 513 lines / 87,140 chars → `PRD_COMPLETED.md` 514 lines / 95,834 chars (**+1 line, +8,694 chars**). All edits are in-paragraph inserts/revisions except one added bullet under §2.2's error-format list.

**Counts:** 32 ambiguity-pins, 4 mismatch-revisions.

### Changes

- **§2.1** — revise — ambiguity — blank/whitespace-only headers also draw `ERR_UNAUTHENTICATED`, not just absent ones — `middleware.py:28-34`
- **§2.2** — insert — ambiguity — off-catalogue transport errors `ERR_NOT_FOUND` (404) and `ERR_METHOD_NOT_ALLOWED` (405) — `app.py:51-63`, `errors.py:77-78`
- **§2.3** — revise — ambiguity — non-integer / out-of-range `limit`, negative `offset` → `ERR_INVALID_REQUEST`; unnamed query params ignored — `validate.py:176-231`
- **§2.3** — revise — ambiguity — `created_at` ties in list ordering broken by insertion sequence — `db.py:149-151`
- **§2.4** — revise — ambiguity — incident listings also filter `triage_class` and `claim_basis`; int/bool filter coercion rules — `routes_money.py:207-216`, `validate.py:198-231`
- **§2.6** — revise — ambiguity — clock may move backwards; response carries `current_utc` alone — `routes_ops.py:100-105`
- **§2.8 step 4** — revise — ambiguity — empty body reads as `{}`, non-object body is `ERR_INVALID_REQUEST`, explicit null counts as absence — `validate.py:136-169`
- **§3.1** — revise — ambiguity — `footprint_units` and `insured_value_cents` are required, not optional — `routes_registry.py:145-146`
- **§3.2** — revise — ambiguity — fresh survey also carries `status` `DRAFT`, `revision_rounds` 0, null `submitted_by_user_id`/`finalized_by_user_id` — `routes_survey.py:61-68`
- **§3.2** — revise — ambiguity — wrong-status photo attach → `ERR_ASSESSMENT_INVALID_STATE`; `media_ref`/`caption` discarded; response is the survey — `routes_survey.py:101-108`
- **§3.2** — revise — **mismatch** — Cascade A hop 3 fires only when hop 2 actually moved the dimension into `TREATMENT_REQUIRED` — `services.py:318-340`
- **§3.3** — revise — ambiguity — a candidate visit's site is its artwork's *current* `site_id`; same-work visits count — `routes_survey.py:203-217`
- **§3.3** — revise — ambiguity — SLA derives from `graffiti_reported_at` alone; protocol `method` never consulted — `routes_survey.py:219-224`
- **§3.3** — revise — ambiguity — `crew_note` on start overwrites the scheduled one when supplied — `routes_survey.py:277-278`
- **§3.4** — revise — ambiguity — vendor suspension is idempotent; re-suspending leaves `version` alone — `routes_registry.py:355-357`
- **§3.4** — revise — ambiguity — draft zeroes `subtotal/overhead/contingency/mobilization`, nulls the user ids, does not store `expected_artwork_version` — `routes_treatment.py:69-81`
- **§3.4** — revise — ambiguity — line append gated to `DRAFT`/`REVISION_REQUESTED` → `ERR_PROPOSAL_INVALID_STATE`; `labor_hours` ≥ 0 non-integral, `materials_cents` ≥ 0; `description` discarded — `routes_treatment.py:111-119`
- **§3.4** — revise — ambiguity — stored line holds exactly five fields; append returns the whole proposal — `routes_treatment.py:123-133`
- **§3.4** — revise — ambiguity — empty `line_items` on submit → `ERR_PROPOSAL_INVALID_STATE`, evaluated at step 9 ahead of the deaccession guard — `routes_treatment.py:144-149`
- **§3.5** — revise — ambiguity — multi-consultation consent resolution (objection dominates; pending only absent concur/lapse); link is by `proposal_id` alone — `routes_treatment.py:176-189`
- **§3.5** — revise — **mismatch** — in-progress-visit collision reported as `ERR_ARTWORK_CUSTODY_INVALID`; conservation moves only from `TREATMENT_REQUIRED`; `IN_STORAGE → IN_TREATMENT` *raises* `installed_units_used` — `routes_treatment.py:277-290`
- **§3.5** — revise — ambiguity — `condition_index` survives treatment completion uncleared — `routes_treatment.py:311-316`
- **§3.6** — revise — ambiguity — named `artist_id` and `proposal_id` need not agree with the work; only resolution is checked — `routes_rights.py:51-53,124-126`
- **§3.6** — revise — ambiguity — consultation created with `response_note` null — `routes_rights.py:66-67`
- **§3.6** — revise — **mismatch** — `consumed_by_ref` is the case `id` for a deaccession but the *artwork's* `id` for a relocation; earliest-created matured notice authorises — `services.py:274-295`, `routes_registry.py:238`
- **§3.7** — revise — ambiguity — exactly one of `to_storage`/`to_site_id`, else `ERR_INVALID_REQUEST` before body FK resolution; `relocation_note` not retained — `routes_registry.py:218-223`
- **§3.7** — revise — ambiguity — a work withdrawn to storage keeps its `site_id` — `routes_registry.py:235-240`
- **§3.8** — revise — ambiguity — case created with `public_comment_opens_on`, `public_comment_closes_at`, `executed_at` null — `routes_rights.py:200-209`
- **§3.8** — revise — ambiguity — `decision_ratio` pinned unrounded; post-tally ballots draw `ERR_CASE_INVALID_STATE` — `routes_rights.py:291-295`, `calc.py:172-176`
- **§3.9** — revise — ambiguity — rank ties settled by insertion sequence; cohort ignores custody, so a deaccessioned `TREATMENT_REQUIRED` work keeps a rank — `services.py:196-213`
- **§3.9** — revise — **mismatch** — rescore pass covers any status/custody and bumps `updated_at`/`version` even on an unchanged score, against §2.5's no-op rule — `routes_ops.py:41-48`
- **§3.10** — revise — ambiguity — the endowment/percent-for-art field convention is unenforced; irrelevant amounts stored and ignored — `calc.py:136-154`, `routes_money.py:34-41`
- **§3.10** — revise — ambiguity — neither link also `ERR_ALLOCATION_LINK_MISMATCH` but only after FK resolution; linked statuses uninspected; `expected_pool_version` unstored — `routes_money.py:94-121`
- **§3.11** — revise — ambiguity — `damage_extent_pct` bound enforced, two-place presentation not; stored as supplied — `routes_money.py:168`
- **§3.11** — revise — ambiguity — claim dimension inspected before damage dimension (`ERR_CLAIM_INVALID_STATE` wins); `credited_pool_id` overwrite semantics — `routes_money.py:246-247,265-266`
- **§4** — revise — ambiguity — all transition notes/refs (incl. mandatory `completion_report_ref`, `rejection_reason`, `ballot_note`, photo `media_ref`) are validated then discarded; only `response_note` and `crew_note` persist — across all route modules

### Notable findings
Three impl behaviors actively contradicted the finalized PRD rather than merely going unstated: starting execution on a **stored** work *increases* the site's footprint usage (PRD said footprint is "deliberately left unchanged"); a relocation writes the **artwork's** id into `consumed_by_ref` because no relocation record exists; and the cycle checkpoint's rescore pass bumps `version` unconditionally, which is the sole violation of §2.5's "a no-op recomputation is not a mutation" guarantee. Cascade A hop 3 is also narrower than the PRD read — it only aborts visits when the finalization itself flipped the conservation dimension.

---

## Pipeline complete — 2026-09-01T10:58:37.000Z

All nine steps ran to completion. Final artifacts on disk: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files), `test_suite/` (conftest + 16 files, 127 tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (17 files incl. `start.sh`) and `workspace/implementation/results.{1..8}.json` — all eight rounds 127/127.
