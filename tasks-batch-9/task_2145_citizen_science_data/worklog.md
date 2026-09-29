# Worklog — task_2145_citizen_science_data

## Step 1: Create task directory — 2026-08-23T03:57:15.316Z

Created `tasks/task_2145_citizen_science_data/` and `tasks/task_2145_citizen_science_data/workspace/`.

## Step 3: Copy shared files — 2026-08-23T03:57:40.000Z

Copied `INSTRUCTION.md` -> `tasks/task_2145_citizen_science_data/workspace/INSTRUCTION.md`.

## Step 2: Generate scaffold — 2026-08-23T04:57:33.815Z

All three artifacts are generated, valid YAML, and lint-clean.

## Files

- `/home/ubuntu/github/CodingPRD/tasks/task_2145_citizen_science_data/SCAFFOLD.yaml` (§1.0–§1.7, 2880 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2145_citizen_science_data/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, 1911 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_2145_citizen_science_data/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, 6249 lines)

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    62
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     80
  Calls scanned (§1.8+§1.9):  1639

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Counts

15 entities · 11 state machines (2 of them the two parallel dimensions of `Observation`) · 3 OCC concurrency rules · 8 calculations · 45 ordered validations · 62 endpoints · 59 error codes · 4 roles. §1.8 = 9 rules × 2 = 18 instances; §1.9 = 80 active instances + 8 `excluded_because` stubs across all nine guide sections. 106 unique instance names, zero collisions.

## Profile (all knobs at the hard end)

`multi_party_negotiation` × `temporal_windowing`; topology `graph`; shape `cyclic`; role model `segregation_of_duties`; layers = OCC + cascading side effects + dual-variant calc + derived-field reconciliation. Weighted multi-expert quorum drives `Observation`, which carries two independent state dimensions plus a bounded revision cycle.

## Difficulty-rule coverage (2 each, differentiation honored)

- **dual_variant** — Observation provisional (rounds `raw`) vs final (multiplies unrounded `raw`) → 60.00 vs 66.00; Volunteer rolling 0.5000 vs decayed lifetime 0.4161.
- **combinatorial** — mode (b) two-stage rounding: coverage 0.1650 vs naive 0.1667; mode (c) pinned-median floor: `quality_floor` 20.48 / `record_count` 3 where a fixed-point re-derivation gives 52.80 / 2.
- **non_linear_sm** — Observation revision cycle; Equipment three-way QUARANTINE fork closing a service cycle.
- **transitive_cascade** — depth-5 reject chain (reject→score→probation→cert suspend→loan cancel) and depth-4 retract chain (retract→publication dim→site/campaign coverage→campaign reopen).
- **priority_pairs** — `state` vs `business_temporal`; `business_safety` vs `business_fiscal` (plus a third, referential vs temporal, in §1.9).
- **boundary** — `quality_score == 0.5000` exactly at `PROBATION_FLOOR` (votes endpoint); zero-site campaign open (campaigns endpoint).
- **cross_entity** — Observation→Campaign; EquipmentLoan→Equipment.
- **temporal_overlap** — Equipment half-open `[start, returned_at+48h)` with adjacency permitted; Protocol closed-inclusive season dates with adjacency forbidden.
- **compensating_invariant** — points ledger (`lifetime_points == Σ awards`, 77→25 with the null-observation MILESTONE deliberately unreversed) and equipment custody count/hour ledger.

## Design adjudications made during generation

1. **`api_prefix: /citizen-science` with a flat two-segment layout.** The lint's collection-segment heuristic only derives a segment from `<prefix>/<seg>/{id}`, and its sub-resource probe builds the literal `{id}` placeholder — so every detail route is `/citizen-science/<collection>/{id}` and every path parameter is named `{id}`. Deeper nesting would have made FK reverse-reachability unprovable.
2. **`ERR_REVISION_LIMIT_REACHED` was unreachable as first drafted** (the consensus ladder auto-rejected at round 2, so `NEEDS_REVISION` at `revision_round == 2` could never exist). Resolved by making REVISE always park in `NEEDS_REVISION`, moving the cap onto `resubmit`, and adding a maintenance-run `NEEDS_REVISION → REJECTED` sweep so the state is not a dead end.
3. **Publication supersede ordering was reversed.** Running `publication_release_metrics` before the supersede left zero candidates; the create side-effects now pin supersede → metrics → bind, and validation 52 says the floor is counted after the predecessor releases its QUEUED rows.
4. **`QUORUM_MIN_VOTES = 2` plus a 0.50–4.00 weight range** — the reject-on-tie rung is otherwise unreachable, since per-vote evaluation resolves before the totals can equalize. Two weight-4.00 experts at confidence 2 produce an exact 3.2000/3.2000 tie.
5. **`PROBATION_FLOOR` lowered 0.60 → 0.50** so the exact-boundary case needs two observations instead of five, and `MIN_RECORD_FLOOR` 3 → 2 to keep publication fixtures tractable.
6. **Retraction deliberately does NOT fire the probation cascade** (only a vote-driven REJECT does), stated explicitly in the transition's side effects — it is a trap the tests assert against.
7. **Photo screening evaluates time before geo**, so a doubly-invalid photo is `REJECTED`, never `FLAGGED_MISMATCH`.
8. All 59 error codes are triggered by at least one recipe; the ten entity-specific 404s are covered by one consolidated instance so each keeps its own `error_id` rather than collapsing to a generic not-found.

## Step 4: Generate PRD — 2026-08-23T05:11:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2145_citizen_science_data/workspace/PRD.md` — **471 lines**, written incrementally in 9 appends (no single oversized Write).

## Coverage tally vs. scaffold

| Element | Scaffold | In PRD |
|---|---|---|
| Entities | 15 | 15 (all narrated across §3.1–3.8) |
| `entities[].fields[]` names | 111 | 111 backticked, 0 missing |
| `request_body`/`input` identifiers | 63 | 63, 0 missing |
| `query_params` identifiers | 27 | 27, 0 missing (enumerated per-collection in §2.3) |
| State machines | 11 | 11 |
| Transitions | 66 | 66 — every non-initial `from -> to` pair appears literally in prose |
| Calculations | 8 | 8, full formulas in business prose (no pseudocode, no fuzzy words) |
| Validations | 45 | 45, in strict priority order (1–12, 20–28, 30–39, 40–53) in §2.7, each with error ID + full `applies_to` set |
| Endpoints | 62 | 62 rows, 4-column table |
| Errors | 59 | 59 rows, 2-column table; all 59 also referenced in §2/§3 narrative |
| Roles | 4 | 4, each `identity:` translated (1 opaque, 3 entity-backed) |
| `concurrency_rules` | 3 | 3, each with write endpoint + `expected_<parent>_version` + exact error ID + 412 |

## Hard Contracts

```
Field coverage check:
- entities[].fields: 111 required, 111 present, 0 missing
- endpoints[].request_body: 63 required, 63 present, 0 missing
- endpoints[].query_params: 27 required, 27 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 45 checked, 45 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed, 0 missing
- state_machines[].transitions: 66 checked, 66 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 45 checked, 45 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 62 checked, 62 expressed, 0 missing
- entities[].fields[] structured content: 111 checked, 111 reconstructible, 0 missing
- sibling-branch symmetry: 6 groups (quarantine 3-way fork, GOOD/DAMAGED vs LOST return,
  RELEASED vs EMBARGOED release, 4-branch consensus ladder, 4-branch coverage_status ladder,
  3-branch photo screening) checked, 6 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 782
- tokens starting with `/`: 0 | bare HTTP-method tokens: 0 | method+path tokens: 0
Status: PASS
```

§2.2 verified byte-identical to `section-2.2-response-structure.md`. PRD ends at §5 with no audit footer.

## Zero-Silence adjudications (6)

1. **Protocol activation's "no other ACTIVE protocol with the same `code`" precondition** carries no `error_id`. Expressed as the invariant activation defends, with a note that global `code` uniqueness satisfies it structurally. No code invented.
2. **Volunteer reinstatement preconditions** (`status` in `{PROBATION, SUSPENDED}`, `quality_score` >= 0.50) carry no `error_id` and no catalogue entry fits. Stated as availability conditions; no code invented.
3. **Loan issue's "logical clock < `due_at`"** precondition carries no `error_id`. Stated as a precondition with business rationale; no code invented.
4. **Start-review's "campaign is `OPEN` or `CLOSED`"** appears in the state machine but not in the 45-rule validation table. Stated in prose without a code.
5. **`QUEUED -> UNPUBLISHED` vs. the candidate-set definition** — the publication_status edge sends freed observations to `UNPUBLISHED`, but `publication_release_metrics` defines candidates as `QUEUED`, which would make "re-enters the candidate pool" impossible. Reconciled by defining the candidate pool as accepted, unbound observations whose `publication_status` is `QUEUED` **or** `UNPUBLISHED`, so both scaffold statements hold simultaneously. This is the only place where PRD wording is broader than a literal scaffold clause.
6. **`total_loan_hours` on a LOST return** — the `Equipment` field definition sums `{RETURNED, LOST}` while the `ON_LOAN -> RETIRED` side-effect list omits it. Followed the field definition (accumulates for both).

Orchestrator verification: 471 lines, 59 unique ERR_ codes present, §5 catalogue intact through last line.

## Step 6: Generate implementation — 2026-08-23T05:32:00.000Z

Implementation complete and verified.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2145_citizen_science_data/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | — | Guarded `pip install` (only when flask missing), `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | — | `flask>=2.0` |
| `app.py` | 80 | Blueprint registration, ApiError/HTTPException handlers, global RLock per request, `/health` |
| `clock.py` | 44 | Logical clock (seeds `2026-08-01T00:00:00Z`, never wall-clock), 3-fraction ISO formatter |
| `db.py` | 96 | 15 in-memory dicts (all start empty), UUID mint, `touch()` (one version bump per row per request), serializer |
| `errors.py` | 134 | All 59 error IDs -> HTTP status |
| `response.py` | 49 | `meta`/`response_type`/`data` envelope, `req_` + 20 alnum, pagination meta |
| `guards.py` | 294 | Admission ladder pieces: auth (1-3), actor (5), 12 not-found lookups (4/7), payload validator (6), pagination/filters, uniqueness (48) |
| `calc.py` | 261 | All 8 calculations + constants, `Decimal`/`ROUND_HALF_UP` throughout |
| `services.py` | 459 | Cascades P/A/R/T/W, coverage arithmetic, publication metrics, half-open occupancy |
| `routes/core.py` | 311 | Protocols, volunteers, experts, certifications |
| `routes/campaigns.py` | 164 | Campaigns + survey sites |
| `routes/observations.py` | 402 | Observations, photo evidence, votes, resubmit, retract |
| `routes/equipment.py` | 239 | Equipment + loans |
| `routes/publications.py` | 319 | Publications, partners, grants, awards |
| `routes/ops.py` | 96 | Maintenance sweep (6 pinned phases), `/_clock/set_current_utc` |

All 62 endpoints implemented. Verified with `python3 -m py_compile` on every file, and four end-to-end smoke suites (~120 assertions) run against fresh servers — all green. Boot via `start.sh` measured at **588 ms**; every collection reports `total_count: 0` on a fresh boot (no seeding anywhere).

## Key fidelity points exercised in testing
- Pinned two-stage coverage rounding (target 3, counts [1,0] -> `0.165`, not `0.1667`)
- Unrounded `raw` carried into `final_quality_points` (54 x 1.1 x 0.85 = **50.49**)
- Drift: `ceil` loan hours -> round base -> add penalties -> round again (11 h DAMAGED -> **208.25**)
- Half-open loan occupancy incl. the 48 h returned-tail; adjacency permitted / season adjacency forbidden
- Ledger invariant `sum(points_awarded) == lifetime_points` survives retraction (MILESTONE rows never clawed back)
- Ladder precedence, e.g. equipment-requirement (33) beating season (40); duplicate-vote (11) and OCC (12) beating review-state (23)

## PRD ambiguities resolved

1. **Re-binding an `UNPUBLISHED` candidate into a new publication.** §3.8 step 2 admits both `QUEUED` and `UNPUBLISHED` candidates, but step 3 only says bound records "stay in `QUEUED`", and release only moves `QUEUED -> PUBLISHED`. Leaving re-pooled records at `UNPUBLISHED` made release silently skip them. **Resolved:** step 3 sets `publication_status = QUEUED` on every included observation, making the stated postcondition true and release coherent. (This was a real bug caught by the smoke suite.)
2. **Candidate-set definition conflict.** SCAFFOLD `publication_release_metrics` requires `publication_status == QUEUED`; PRD §3.8 says `QUEUED` *or* `UNPUBLISHED`. **Resolved in favour of the PRD** (the scaffold version would make supersession release records into a pool that can never be re-collected).
3. **Reinstate preconditions have no error ID.** §3.2 requires status in {PROBATION, SUSPENDED} and `quality_score >= 0.50`, but neither §2.7 nor §5 assigns an error. **Resolved:** `ERR_VOLUNTEER_NOT_IN_GOOD_STANDING` (403) — the only volunteer-standing error in the catalogue.
4. **Approving a grant against a non-RELEASED / non-EMBARGOED publication.** §3.8 requires RELEASED-or-EMBARGOED but the ladder's priority 25 excludes grant-approve. **Resolved:** `ERR_PUBLICATION_STATE_INVALID` (409), evaluated *last* (after 26/27/38/39/46/47) so it can never mask a specified error.
5. **Issuing a loan whose `due_at` has already passed.** Scaffold precondition `clock < due_at` with no error ID. **Resolved:** `ERR_LOAN_STATE_INVALID` (409), checked after the calibration check (44).
6. **Approving an already-`APPROVED` partner.** No partner-state error exists. **Resolved:** `ERR_PARTNER_NOT_APPROVED` (409).
7. **`start-review` on a `PLANNED`/`PUBLISHED`/`ARCHIVED` campaign.** §3.6 states the rule; the ladder's priority 22 excludes start-review. **Resolved:** `ERR_CAMPAIGN_NOT_OPEN` (409), evaluated after priority 50 so it never masks a ladder error.
8. **Body-FK resolution order (priority 7).** Unspecified. **Resolved:** the order the priority-7 `error_id` list itself enumerates (PROTOCOL -> VOLUNTEER -> EXPERT -> CAMPAIGN -> SITE -> EQUIPMENT -> LOAN -> PUBLICATION -> PARTNER).
9. **`recognition_tier` on rejection/retraction.** Only the acceptance chain (§3.7 link 4) re-derives it; the rejection and retraction chains say "recomputes both quality scores" and nothing about the tier. **Resolved literally:** the tier is re-derived only on acceptance.
10. **Multiple valid certifications for one protocol.** §3.5 says "a certification"; **resolved** by taking the highest-ranked valid one for the level test (priority 32), and by treating *any* certification of the observer for that protocol naming the acting expert as a trainer conflict (priority 10).
11. **Datetime echo format.** Input datetimes (`calibration_valid_until`, `observed_at`, `expires_at`, ...) are **normalised** to the §2.4 canonical `...T..:..:...000Z` form rather than echoed verbatim, matching the document's single stated timestamp format.
12. **Version bumps within one request.** §2.4 says version advances by exactly 1 "on every mutation". Where a single request mutates the same row through several links (e.g. a vote that both stores tallies and resolves acceptance), the row is bumped **once per request**, matching every endpoint's "increments X.version by 1" side-effect line. Cascaded rows are bumped only when their values actually change.

## Step 5: Generate unit tests — 2026-08-23T06:05:00.000Z

Test infrastructure and suite generated and verified.

## Files written

**`test_helpers/`** (9 modules, ~1,700 lines)
- `types.py` — 22 status/role enums + entity TypedDicts. `VerificationVote` and `RecognitionAward` carry only `id` + `created_at` (no `updated_at`/`version`), per the PRD's append-only exception.
- `api_client.py` — `ApiClient(GenericApiClient)`, one method per endpoint in §4 plus `/_clock/set_current_utc` and raw dispatch helpers for header-level negative tests.
- `api_errors.py` — all 59 `ApiErrorId` members + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, ISO-8601-with-millis and bare-UUID checkers, `assert_points_ledger_conserved`, `assert_coverage_consistent`.
- `constants.py`, `factories.py`, `test_users.py` (per-instance builders for the three entity-backed roles), `fixtures.py`, `__init__.py`.
- `fixtures.py` is the load-bearing piece: a staged `build_world(stage=1..9)` (clock -> active protocol -> volunteer + 3 experts -> ENROLLED -> TRAINED -> CERTIFIED -> campaign -> site -> OPEN) that reproduces every prefix the two indices use (`BASE x1/x3/x7/x10/x11/x12/x13`), plus observation-lifecycle, equipment-custody and publication/partner tiers.

**`test_suite/`** — `conftest.py` + 9 domain-named files, **116 tests**.

## Coverage

| Queue | Instances | Tests | Result |
|---|---|---|---|
| A — Difficulty | 18 | 36 | every instance has exactly 2 tests |
| B — Corner | 80 non-stub | 80 | every instance has 1 test |

Audited programmatically: 0 untagged, 0 dual-tagged, 0 bogus tags, 0 shortfalls. All 8 `excluded_because:` stubs were left untranslated and their `difficulty_instance` cross-references resolve to real queue-A instances.

## Verification performed

- `python3 -m py_compile` on all 19 files; `pytest --collect-only` collects 116 tests with no import errors; pyflakes clean on `test_suite/`.
- **PRD-citation pass**: 245 quoted citations extracted from docstrings and matched verbatim (whitespace-normalised) against `workspace/PRD.md` — 0 failures; every test carries at least one >=8-word citation.
- No `skip`/`skipif`/`xfail`; no "scaffold"/table/§1.x references in generated code.

## Instances skipped

**None.** All 18 difficulty instances and all 80 non-stub corner instances passed the PRD-first two-condition filter.

Two individual sub-assertions were dropped (the instances themselves are still covered):

1. `Difficulty/dual_variant_calc/volunteer_rolling_vs_lifetime_quality_score_diverge` — the yaml asserts `recognition_tier == BRONZE` after the rejection. PRD §3.7 re-derives `recognition_tier` only in the **acceptance** chain's fourth link; the rejection chain's second link says only "recomputes both quality scores". A faithful PRD-only implementer could leave the tier at `PLATINUM`, so that assertion fails unique derivability (`branch-asymmetry`). The two tests still assert the divergent scores (0.5000 vs 0.4161), status, and both counters.
2. `Corner/entities/volunteer_system_fields_are_server_generated` — the yaml asserts `updated_at == created_at` and `Corner/entities/verification_vote_is_append_only_with_no_version_field` asserts "no PUT/PATCH/DELETE endpoint is declared". Neither is PRD-stated (the first is inferable but not written; the second is not observable through the declared surface). Both tests assert the PRD-covered parts instead — `version == 1`, seeded fields, ISO-8601-with-three-fractional-digits format, and the vote row's absence of `updated_at`/`version`.

## Step 7: Test-and-fix loop — 2026-08-23T06:20:00.000Z

**Iterations run:** 2 (each = 8 concurrent full rounds, 116 tests, `per-test-server` isolation).

- **Iteration 1:** 115/116 in all 8 rounds — one deterministic failure, `test_05_expert_verification.py::test_earlier_round_votes_are_retained_but_stop_counting` (`AssertionError: Round 1 holds no votes yet, got 3.2`).
- **Iteration 2:** **116/116 in all 8 rounds.** No flakiness surfaced in either sweep (the suite contains no race/concurrency tests, so the failure set was identical across all rounds both times).

**Tests deleted:** none.

**Assertions removed under STEP 1c (partial coverage):** one, inside `test_suite/test_05_expert_verification.py::test_earlier_round_votes_are_retained_but_stop_counting`.

- Removed: `revision_weight == 0.0000` immediately after `POST .../resubmit`.
- Category: **branch-asymmetric side effect**. §3.6 renders the vote branch fully ("**Consensus** is *then* recomputed over the current round alone", i.e. after each accepted vote is stored) while enumerating resubmit's on-success effects exhaustively and *not* among them: "On success `revision_round` increments by one, `submitted_at` is re-stamped from the logical clock, and `provisional_quality_points` is recomputed from the new `submitted_at`." §2.10's enumeration of denormalized/derived fields lists the volunteer counters, expert `vote_count`/`retracted_confirm_count`, site and campaign coverage fields, publication `record_count`/`mean_quality`, partner `active_grant_count`, and instrument `total_loan_hours` — the observation weight tallies and `consensus_confidence` are **not** in it. Two PRD-faithful readings therefore exist: (A) consensus is recomputed only at vote time, so the tallies keep their round-0 values until the next vote (what the implementation does); (B) the tallies are standing mirrors of the current round, so resubmit zeroes them. Unique derivability broken -> assertion removed.
- Scaffold rule that drove the test's generation: `Difficulty/non_linear_state_machine/observation_revision_cycle_returns_to_submitted`. Note the scaffold's own `NEEDS_REVISION -> SUBMITTED` `side_effects` list likewise does not include a tally reset, confirming the assertion was not design-backed either.

**Fixes applied to `test_suite/`:**

- `test_suite/test_05_expert_verification.py`, `test_earlier_round_votes_are_retained_but_stop_counting` — replaced the non-derivable zero-tally assertion with a PRD-verbatim, uniquely-derivable check of the same rule the test is named for: after resubmit, start review again and cast one round-1 `REQUEST_REVISION` vote at confidence 2, then assert `revision_round == 1`, `revision_weight == 1.6000` (only the single round-1 vote counts; the two round-0 votes at 1.6000 each are never re-summed), `total_count == 3`, and round numbers `[0, 0, 1]`. This directly exercises §3.6's "Only votes whose `round_number` equals the observation's current `revision_round` participate; votes from earlier rounds are retained for audit and are never re-summed." Also added the matching verbatim citation to the docstring, dropped the now-unused §2.10 citation, and added `start_review` to the module's `test_helpers` import list.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `implementation/`:** none. No implementation check was weakened, no endpoint/field/side-effect was added, and storage remains in-memory with no startup seeding.

*Orchestrator note: the Step 7 agent removed its `results.*.json` files on exit; the orchestrator re-ran an independent 8-round sweep to regenerate them and confirm the green claim.*

### Orchestrator verification sweep — 2026-08-23T06:55:00.000Z

Independent 8-round parallel re-run (`prd-bench-local-run --isolation per-test-server`, 116 tests, ~149 s/round):

```
results.1.json passed=116 failed=0 errors=0 total=116
results.2.json passed=116 failed=0 errors=0 total=116
results.3.json passed=116 failed=0 errors=0 total=116
results.4.json passed=116 failed=0 errors=0 total=116
results.5.json passed=116 failed=0 errors=0 total=116
results.6.json passed=116 failed=0 errors=0 total=116
results.7.json passed=116 failed=0 errors=0 total=116
results.8.json passed=116 failed=0 errors=0 total=116
ALL GREEN
```

Step 7's clean-exit claim confirmed. (Two earlier orchestrator attempts used a bare `bash start.sh` start-command; the per-test respawn resolves the command from pytest's rootdir, not the launching shell's cwd, so it exited 127. Corrected to the canonical `cd <impl> && bash start.sh` form — an orchestrator invocation bug, not an implementation defect.)

## Step 8: Finalize PRD — 2026-08-23T06:58:00.000Z

Done. `PRD_FINALIZED.md` written with exactly one edit.

## Line counts
- `PRD.md`: 471 lines / 101,597 bytes
- `PRD_FINALIZED.md`: 471 lines / 102,027 bytes
- Line delta: **0 (0.00%)** — the edit extends one existing paragraph in place. Byte delta: +430 (+0.42%).

## Changes
- **§3.6 (Expert Verification, Weighted Consensus and the Revision Cycle), resubmit paragraph** — *insert* — after the existing sentence "Votes from the earlier round remain on file but stop counting, since consensus only ever sums the current round.", added that resubmission does not itself recompute consensus and resets none of the stored tallies: `confirm_weight`, `reject_weight`, `revision_weight`, and `consensus_confidence` are recomputed only when a vote is stored, so immediately after a resubmission they still show the previous round's values until the first vote of the new round overwrites them — `implementation/routes/observations.py:381-388` (resubmit's on-success block: sets `review_status`, `revision_round`, `submitted_at`, `provisional_quality_points`, then `db.touch`; never calls `calc.consensus`), against `implementation/routes/observations.py:315` (`calc.consensus` is invoked at the vote site only).

## Pre-edit search log

**Edit 1**
- **(a) Subject identified:** the four stored consensus tally fields on `Observation` (`confirm_weight`, `reject_weight`, `revision_weight`, `consensus_confidence`) — specifically *when* they are written/reset, across the whole observation lifecycle, not only at resubmit.
- **(b) Impl paths enumerated (grepped/read):**
  - `grep -rn "consensus_confidence\|confirm_weight\|reject_weight\|revision_weight" --include=*.py` over `implementation/` — exactly 4 write sites plus 2 read sites, all accounted for below.
  - `routes/observations.py:137-140` — observation creation seeds all four to `0.0000` (initialization).
  - `routes/observations.py:315` — vote casting, the **only** callsite of `calc.consensus`.
  - `calc.py:181-224` (`consensus`) — filters votes to `round_number == revision_round`, writes all four fields, then runs the resolution ladder.
  - `routes/observations.py:337-388` (`resubmit_observation`) — the Step 7 site; the four fields are not among the fields it mutates.
  - `services.py:213-271` (`apply_retraction`, the retraction chain) — mutates review/publication status, publication counters, coverage, ledger, volunteer counters, expert `retracted_confirm_count`; does not touch the tallies.
  - `routes/ops.py:42-47` (maintenance sweep, exhausted-revision `NEEDS_REVISION -> REJECTED` via `services.apply_rejection`) — does not touch the tallies.
  - `routes/campaigns.py:110` and `calc.py:108` — read-only consumers (`in_flight` check; `final_quality_points` reads `consensus_confidence`); both consistent, since at acceptance time the tallies were just refreshed by the deciding vote.
  - `PRD.md` §2.10's enumeration of denormalized/derived fields — confirmed the tallies are *not* in that list, so the new sentence creates no conflict with "always correct at the moment a read observes them".
- **(c) Wording adjustment made:** the first draft read "are written only when a vote is stored", which would have falsely excluded the creation-time seeding at `routes/observations.py:137-140`. Changed to "are **recomputed** only when a vote is stored", which leaves the initial seed as plain initialization and stays true of the retraction chain and the maintenance sweep, neither of which recomputes them either. Also phrased the resubmit claim as a negative ("does not itself recompute ... none of the stored tallies is reset by it") rather than asserting any positive new value, so the sentence stays under-determined about what the retained values happen to be.

## Step 9: Complete PRD — 2026-08-23T07:12:00.000Z

Done. Server smoke-tested to confirm the riskier claims before writing them.

## Summary

**Files** — source `PRD_FINALIZED.md`: 471 lines / 101,994 chars -> `PRD_COMPLETED.md`: 471 lines / 108,748 chars (**+6,754 chars, +0 lines**). All 35 changes are in-paragraph inserts/revisions on 35 existing lines; no new sections, paragraphs, or table rows (headers and 125 table rows byte-identical).

**Counts** — 35 changes: **29 ambiguity-pins**, **6 mismatch-revisions**.

Empirically verified against a live server: datetime normalisation (`+02:00` -> `...08:00:00.000Z`, `.5Z` -> `.500Z`), version-once-per-request (obs 3->4 across consensus + acceptance touches; volunteer 2->3; campaign 3->4), vote -> 201 with the `VerificationVote` row (no `updated_at`/`version`), `ERR_PARTNER_NOT_APPROVED`/`ERR_VOLUNTEER_NOT_IN_GOOD_STANDING`/`ERR_INVALID_REQUEST` codes, FK order, `verification_weight` 2.345->2.35 vs `priority_weight` 1.234 stored verbatim.

All 12 claims from the impl generator's report were confirmed in code; #2 (candidate pool = `QUEUED` or `UNPUBLISHED`) needed no change — §3.8 already pinned it.

### Changes

- §2.3 — insert — ambiguity — non-integer `limit`/`offset` also `ERR_INVALID_REQUEST` — `guards.py:236-250`
- §2.3 — insert — ambiguity — `created_at` ties fall back to insertion order — `db.py:245-250`
- §2.3 — insert — ambiguity — filters compare as text (integers numerically); no match = empty page, not an error — `guards.py:265-275`
- §2.4 — insert — ambiguity — tie-break generalised to every `created_at` sort, following the surrounding direction; client instants normalised to canonical 3-digit UTC; season bounds echoed as bare `YYYY-MM-DD` — `guards.py:114-126`, `clock.py:151-161`, `routes/campaigns.py:56`
- §2.4 — revise — **mismatch** — `version` advances at most once per request; a row created by the request stays at 1; `updated_at` refreshed on every touch — `db.py:231-242`
- §2.8 — revise — **mismatch** — a cascade link that recomputes to the value already held leaves `version`/`updated_at` alone — `services.py:70-98`
- §2.7 p7 — insert — ambiguity — multiple body FKs resolved in the enumerated error-list order — `routes/observations.py:60-65`, `routes/equipment.py:120-121`, `routes/publications.py:207-208`
- §2.7 p10 — insert — ambiguity — any certification on that protocol naming the acting expert is a trainer conflict, whatever its `status` — `routes/observations.py:275-280`
- §2.7 p22 — insert — ambiguity — start-review needs `OPEN`/`CLOSED` -> `ERR_CAMPAIGN_NOT_OPEN`, evaluated after p50 — `routes/observations.py:248-249`
- §2.7 p24 — insert — ambiguity — instrument must be `AVAILABLE` at issue -> `ERR_EQUIPMENT_STATE_INVALID`, right after the loan-state test — `routes/equipment.py:181-183`
- §2.7 p25 — insert — ambiguity — grant-approve publication must be `RELEASED`/`EMBARGOED` -> `ERR_PUBLICATION_STATE_INVALID`, evaluated last — `routes/publications.py:278-279`
- §2.7 p27 — insert — ambiguity — partner-approve on a non-`PENDING`/`SUSPENDED` partner -> `ERR_PARTNER_NOT_APPROVED` (409) — `routes/publications.py:187-188`
- §2.7 p30 — insert — ambiguity — both reinstate preconditions -> `ERR_VOLUNTEER_NOT_IN_GOOD_STANDING` (403), standing tested first — `routes/core.py:153-156`
- §2.7 p32 — insert — ambiguity — highest-ranked certification that passed p31 is the one tested — `routes/observations.py:87-88`
- §2.7 p41 — insert — ambiguity — lag is signed, so a future `observed_at` always clears the bar — `routes/observations.py:111-113`
- §2.7 p44 — insert — ambiguity — elapsed `due_at` -> `ERR_LOAN_STATE_INVALID`, directly after the calibration check — `routes/equipment.py:188-189`
- §3.2 — insert — ambiguity — `verification_weight` rounded half-up to 2 dp on storage — `routes/core.py:187`
- §3.3 — insert — ambiguity — inverted season dates -> `ERR_INVALID_REQUEST` at p6, before `protocol_id` resolves — `routes/campaigns.py:39-42`
- §3.3 — revise — **mismatch** — coverage stage two recounts the campaign's `accepted_observation_count` wholesale — `services.py:86-96`
- §3.3 — insert — ambiguity — site `priority_weight` stored exactly as supplied, not re-quantised — `routes/campaigns.py:146`
- §3.4 — insert — ambiguity — `due_at` <= `start_at` -> `ERR_INVALID_REQUEST` at p6 — `routes/equipment.py:117-118`
- §3.4 — insert — ambiguity — the four issue bars in order, with their two distinct error ids — `routes/equipment.py:179-189`
- §3.5 — insert — ambiguity — an `equipment_loan_id` supplied under `NONE` is still FK-checked and recorded, never checked further — `routes/observations.py:64-65, 92-98`
- §3.5 — insert — ambiguity — no review-state precondition guards a photo upload — `routes/observations.py:167-181`
- §3.6 — insert — ambiguity — start-review campaign refusal is `ERR_CAMPAIGN_NOT_OPEN` and is the last bar raised — `routes/observations.py:248-249`
- §3.6 — insert — ambiguity — a vote answers with the created `VerificationVote` at 201, not the observation — `routes/observations.py:326`
- §3.6 — revise — **mismatch** — revision comments are read off the vote rows via the vote list; no feedback field is written onto the observation — `routes/observations.py:322-324`
- §3.7 — insert — ambiguity — `recognition_tier` re-derived only on acceptance, never on rejection or retraction — `services.py:154-162` vs `178-183`, `254-258`
- §3.7 — revise — **mismatch** — retraction recomputes `mean_quality` over bound rows still `QUEUED`/`PUBLISHED`; the retracted row keeps its `publication_id`; falls back to 0.00 — `services.py:229-236`
- §3.7 — insert — ambiguity — the `REVERSAL` row itself carries the retracted observation's `observation_id` — `services.py:251`
- §3.8 — insert — ambiguity — where several prior publications qualify, the most recently created is superseded — `services.py:286-293`
- §3.8 — revise — **mismatch** — step three *sets* `publication_status` to `QUEUED`, re-binding a row step one had returned to `UNPUBLISHED` — `routes/publications.py:86-89`
- §3.8 — insert — ambiguity — approving an already-`APPROVED` partner -> `ERR_PARTNER_NOT_APPROVED` — `routes/publications.py:187-188`
- §3.8 — insert — ambiguity — the publication-state gate on grant approval runs last, after trust-tier/DUA/expiry/embargo — `routes/publications.py:278-279`
- §3.8 — insert — ambiguity — admin revoke and sweep expiry decrement `active_grant_count` but never suspend the partner — `routes/publications.py:297-300`, `routes/ops.py:382-385`
