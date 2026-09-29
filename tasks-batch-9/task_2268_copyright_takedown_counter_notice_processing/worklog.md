# Worklog — task_2268_copyright_takedown_counter_notice_processing

## Step 1: Create task directory — 2026-09-01T14:00:09.377Z

Created `tasks/task_2268_copyright_takedown_counter_notice_processing/` and `workspace/` subdirectory (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T15:40:00.000Z

All three artifacts are complete and lint-clean.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2268_copyright_takedown_counter_notice_processing/`

| File | Lines | Content |
|---|---|---|
| `SCAFFOLD.yaml` | 3509 | §1.0–§1.7: 15 entities, 16 state machines + 3 §1.2.1 concurrency rules, 10 calculations, 35 priority-ordered validations, 71 endpoints, 58 error codes, 5 roles |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1874 | §1.8: 18 instances — exactly 2 per §0.5 difficulty rule_id |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 6005 | §1.9: 89 instances across all 9 taxonomy sections (76 with full `test_recipe`, 13 `excluded_because` pointers into §1.8) |

Profile: `role_model: segregation_of_duties`, `entity_topology: graph`, `state_machine_shape: parallel`, `consistency_model: immediate`, layers = cascading_side_effects / rate_threshold_triggers / dual_variant_calculation / optimistic_concurrency.

## Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    71
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     76
  Calls scanned (§1.8+§1.9):  1513

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Verified coverage (scripted checks)

- All 108 instance names unique across both design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 name; no excluded instance carries a `test_recipe`.
- All 58 error codes are triggered by at least one recipe (the 15-member `*_NOT_FOUND` family via one sweep instance; the state family via two multi-aggregate sweeps).
- All 62 state-machine transitions are exercised; all 71 endpoints are exercised (63 as real calls, 8 nested reads inside assertion prose); all 15 entities, 10 calculations and 5 roles appear.

## Three coherence defects found and fixed in SCAFFOLD.yaml

1. **`ERR_RESTORATION_BLOCKED_BY_SUIT` was unreachable** — `record-suit-notice` atomically upheld the claim on both CounterNotice rows, so no claim could ever be `RESTORATION_SCHEDULED` under a `BLOCKED_BY_SUIT` counter-notice. The two paths are now split (pre-window suit → immediate uphold; post-window suit → claim stays scheduled) and a guarded `POST /dmca/claims/{id}/uphold` finaliser was added that accrues no second strike.
2. **`ERR_APPEAL_WINDOW_CLOSED` was masked** — the `EXECUTED→CLOSED` auto-close fired "at or after" `appeal_deadline_at`, so `file-appeal` always hit `ERR_INVALID_TERMINATION_STATE` first. The auto-close is now *strictly after* the deadline, creating a clean boundary at exactly `appeal_deadline_at`.
3. **`POST /dmca/accounts/{id}/reinstate` had no reachable success path** — its precondition ("no TerminationCase is EXECUTED") could never hold for a TERMINATED account, and it contradicted the auto-close note. Reinstatement is now gated on recomputed `strike_points` falling strictly below `limitation_threshold_points` (reachable only after decay/expiry), and the error catalog + endpoint description were updated to match.

Also added the missing `response_envelope.list_ordering` convention (created_at ASC, filter-before-paginate, filters intersect) that the listing assertions depend on, and corrected two stale prose values (`appeal window 30 days` → 14; calculation header variant count).

## Step 3: Copy shared files — 2026-09-01T15:41:58.325Z

Copied `INSTRUCTION.md` → `tasks/task_2268_copyright_takedown_counter_notice_processing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T15:59:30.000Z

PRD written and all three Hard Contracts verified.

**Deliverable:** `workspace/PRD.md` (463 lines, ~13.6k words)

**Structure:** 5 top-level sections; §2 has 11 domain-derived subsections (RBAC, response structure, pagination/filtering, identity + logical clock, path resolution, the 19-rung rejection ladder, OCC, arithmetic precision, parallel state dimensions, safe-harbour gates, cascade discipline); §3 has 9 workflow subsections; §4 is a 4-column table of all 71 endpoints; §5 is a 2-column table of all 58 errors. §2.2 is a byte-exact copy of `section-2.2-response-structure.md`.

```
Field coverage check:
- entities[].fields: 164 required, 164 present, 0 missing
- endpoints[].input identifiers (request_body + query_params + path_params): 125 required, 125 present, 0 missing
- endpoints[].output shapes (incl. strike-summary computed read): 9 required, 9 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 77 checked, 77 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 58 checked, 58 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 89 endpoint clauses + 119 transition clauses checked, all expressed, 0 missing
- entities[].fields[] structured content: 164 checked, 164 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked, 14 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 849
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verified invariants: every §4 row's `Authorized Role(s)` cell matches the scaffold's `roles` list exactly (71/71, no extras, no omissions); every §5 status code matches the scaffold's `http` value (58/58); no pseudocode operators (`>=`, `+=`, `round(`, `AND`, `IN`, …) and no fuzzy quantifiers appear outside the fixed JSON blocks.

Two scaffold ambiguities were resolved and rendered explicitly rather than papered over:
- **`record-suit-notice`** — the endpoint's `side_effects` describe only the `FORWARDED` path, while the state machines define two distinct branches. Both are specified at equal density in §3.7: from `FORWARDED` the claim moves to `UPHELD` and dispute becomes `RESOLVED`; from `RESTORATION_SCHEDULED` the claim *stays* `RESTORATION_SCHEDULED` (restoration blocked, not cancelled), which is why `restore` answers `ERR_RESTORATION_BLOCKED_BY_SUIT` at rung 15 rather than an invalid-state error, and only `uphold` finalises it.
- **`overdue_restoration_count`** — the entity comment and the calculation's `input_set` differ. The calculation's definition (`FORWARDED` or `RESTORATION_SCHEDULED` with `restoration_deadline_at` at or before the clock) is used as primary, with a note that such claims are by construction not restored.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced. No report or summary files were written.

## Step 5: Generate unit tests — 2026-09-01T16:30:00.000Z

Test generation for `task_2268_copyright_takedown_counter_notice_processing` is complete and verified.

## Stage 1 — `test_helpers/` (9 modules, 2,228 lines)

- `types.py` — Role enum, 20 status vocabularies, rejection/gate reason prefixes, TypedDicts for all 15 entities (`SafeHarborAudit` is the sole append-only shape: `id` + `created_at` only)
- `api_client.py` — one method per endpoint: all 71 `/dmca` routes plus `POST /_clock/set_current_utc` (not under the prefix), ending with module-level `api_client = ApiClient()`
- `api_errors.py` — `ApiErrorId` with all 58 ids + `HTTP_STATUS_CODES`, registered via `set_error_http_status_map`
- `constants.py` — every pinned calculation constant (notice/counter weights and thresholds, strike decay factors and tier weights, restoration business-day window + holidays, penalty tiers, safe-harbor components, match confidence weights, abuse weights, ingestion window), policy/quota defaults, `TEST_DEFAULTS`
- `test_users.py` — 7 identities plus `make_rights_holder_rep_headers` / `make_subscriber_headers` for the two `entity_backed` roles
- `factories.py`, `assertions.py` (per-entity shape checks + `assert_instant_equals`), `fixtures.py` (provider documentation chain, scene builders like `setup_documented_provider` / `setup_disabled_claim`), `__init__.py` barrel

`python -c "import test_helpers"` succeeds; error-status map registers all 58 ids.

## Stage 2 — `test_suite/` (conftest + 9 files, 126 tests)

| File | Tests | Design source |
|---|---|---|
| `test_01_entity_creation_and_field_semantics.py` | 13 | Corner/entities |
| `test_02_state_machine_transitions.py` | 17 | Corner/state_machines |
| `test_03_scoring_and_penalty_arithmetic.py` | 10 | Corner/calculations |
| `test_04_validation_rules_and_endpoint_contracts.py` | 12 | Corner/validations + endpoints |
| `test_05_error_catalogue.py` | 13 | Corner/errors |
| `test_06_access_control_and_consistency.py` | 11 | Corner/rbac + cross_cutting + consistency_model |
| `test_20_compliance_variants_and_component_formulas.py` | 18 | Difficulty (dual_variant_calc, combinatorial_formula, non_linear_state_machine) |
| `test_21_cascades_and_rejection_precedence.py` | 18 | Difficulty (transitive_cascade, priority_pair_validation_conflict, boundary_precision_check) |
| `test_22_cross_entity_gates_windows_and_invariants.py` | 14 | Difficulty (cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant) |

## Verification

- Coverage: **difficulty 18/18**, **corner 76/76 non-stub** (15 `excluded_because` stubs correctly untested), 94 distinct `Design:` tags across 126 tests
- Exactly one `Design:` line per test; every tag resolves to a real instance in the correct `rule_id`/`section`; no stub is tagged
- PRD-citation pass: every quoted docstring span >=40 chars appears verbatim in `workspace/PRD.md` after whitespace normalization — clean
- Scaffold-citation pass: `grep -rniE "scaffold|§1\.[0-9]|Table [0-9]|design_index|test_recipe|distinguishing_aspect|rule_id"` over both directories — empty
- `python -m pytest test_suite --collect-only -q` → 126 collected; pyflakes clean
- **Zero instances skipped for PRD gaps.**

## Adjudication caveats (all resolved in favour of what the PRD uniquely derives)

1. Two ordering instances advance the clock between sibling creations, because PRD §2.3 breaks ties on `created_at` alone and never consults `id`.
2. One corner instance's assert block was internally self-contradictory (claim `RESTORATION_SCHEDULED` vs. counter-notice "still FORWARDED"); only the PRD-derivable half is asserted.
3. One instance expected `412` on a replayed agent registration, but PRD §2.6 ranks state legality (rung 11) above OCC (rung 19), so `ERR_INVALID_AGENT_STATE` (409) is what the PRD derives; a different PRD-pinned rejected write covers the stale-version leg.
4. Misrepresentation case-count assertions after substantiation were omitted — the PRD does not settle whether the 40-point auto-open threshold fires on that recompute.
5. `iso()`/`shift_iso()` render whole seconds, so millisecond-precision instants are passed as literals.
6. **Design-index defect (harmless):** corner stub `duplicate_claim_is_detected_from_the_still_open_dispute_interval` cites `errors[ERR_DUPLICATE_ACTIVE_CLAIM]`, which is not in the PRD's 58-error catalogue (the real code is `ERR_DUPLICATE_CLAIM_WINDOW`). No test depends on it since the instance is a stub. All 15 stubs' `difficulty_instance` cross-references were otherwise confirmed to resolve.

## Step 6: Generate implementation — 2026-09-01T16:30:00.000Z

Implementation complete and green.

## Result

`prd-bench-local-run --isolation per-test-server` against `test_suite/` (126 tests, one fresh server boot per test): **126/126 passed** in 167 s.

## Deliverable

`workspace/implementation/`

- `start.sh` (executable) — guarded `pip install` (only when Flask is missing, so concurrent per-test reboots don't contend), then `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000). Real-process boot measured at ~1 s.
- `app.py` — app factory, `/dmca` prefix, unprefixed `/_clock/set_current_utc`, error handlers for `ApiError` / `HTTPException` / bare `Exception`. 71 declared routes.
- `store.py` — in-memory store, boots empty, logical clock pinned to `2026-08-01T00:00:00Z`.
- `envelope.py`, `errors.py` (58-entry catalogue), `guards.py` (rejection-ladder rungs 1-6), `calc.py` (10 calculations), `services.py` (cascades, posture, strike accounting, clock side effects), `routes_core.py`, `routes_notice.py`.

## Two fixes made this session

1. `routes_notice.py` / `routes_core.py`: verified and exercised the last untested branch — `ERR_DUPLICATE_CLAIM_WINDOW` now confirmed reachable via restore-then-reclaim (item back to `RESTORED` while the `(content_item, rights_holder)` interval is still occupied), distinct from `ERR_NO_ACTIONABLE_CLAIMS`.
2. `test_helpers/assertions.py:149` — **the only change outside the implementation**. `assert_claim` called `assert_four_decimal_places(data["match_confidence"])` unconditionally, which contradicts PRD §3.6 ("When no candidate reaches the floor — or the holder has no active reference file at all — the claim is still created ... with both `reference_file_id` and `match_confidence` left null") and contradicted two sibling tests in the same suite that assert `match_confidence is None` (`test_01:490`, `test_21:214`). This was the sole cause of the two failures (`test_restore_one_millisecond_before_the_due_instant_is_too_early`, `test_process_requires_a_published_repeat_infringer_policy`). Made the check conditional, plus an added invariant that null confidence implies null `reference_file_id`. No implementation behaviour was bent to satisfy a test.

## Note for whoever runs the harness

`--start-command` must be an **absolute** path. The per-test restart path in `pytest_plugin.py::_restart_server` resolves cwd from the pytest process (the test dir), not the runner's cwd, so a relative `workspace/implementation/start.sh` produces 126 spurious "could not be restarted" errors.

## Step 7: Run tests and iterate — 2026-09-01T16:36:00.000Z

Clean sweep on the first iteration. Verified the result is not an artifact: storage is pure in-memory dicts (`Store.reset()` sets every collection to `{}` and pins the clock to the epoch), there is no SQLite/JSON/`/tmp` persistence anywhere in `workspace/implementation/`, no entity is seeded at boot, and the suite contains no `skip`/`xfail` markers (the only grep hits were a test *name* containing "skips" and its Design tag).

## Summary

**Iterations run:** 1 (single 8-round parallel stability sweep).

**Result:** all 8 concurrent rounds returned `126 / 126` passed, 0 failed, 0 errors, ~177 s each. The union of failing tests across all 8 rounds is empty, so no flakiness signal surfaced — no timing-sensitive race, fixture-ordering, or port-collision failure appeared in any round.

**Tests deleted:** none. No test failed in any round, so the STEP 1 coverage / unique-derivability protocol was never triggered.

**Fixes applied to `test_helpers/`:** none this session.

**Fixes applied to `implementation/`:** none this session.

Notes for the caller:
- The sweep command must use the absolute `--start-command` path as documented; a relative path yields 126 spurious "could not be restarted" errors (already recorded in `worklog.md`).
- The results files from this sweep are at `workspace/implementation/results.{1..8}.json`.
- The prior session's worklog (Step 6) records the only test-side change ever made on this task: `test_helpers/assertions.py:149` made `assert_four_decimal_places(data["match_confidence"])` conditional, because PRD §3.6 states a claim may be created "with both `reference_file_id` and `match_confidence` left null". That fix is still in place and consistent with the green sweep.

Orchestrator verification: all 8 `results.{i}.json` re-read independently — `126/126 passed, failed=0` in every round.

## Step 8: Finalize PRD — SKIPPED — 2026-09-01T16:40:00.000Z

Skip condition met: Step 7 exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. No `PRD_FINALIZED.md` produced; Step 9 therefore starts from `workspace/PRD.md`.

## Step 9: Complete PRD — 2026-09-01T16:55:00.000Z

Final verification done: all 42 in-paragraph edits are present (39 diff hunks — several logical pins landed inside the same paragraph), and the line count is unchanged, confirming no new paragraphs or sections were added.

## Metrics

| | Lines | Chars |
|---|---|---|
| Source `PRD.md` (no `PRD_FINALIZED.md` present) | 463 | 99,252 |
| `PRD_COMPLETED.md` | 463 | 107,356 |
| Delta | 0 | **+8,104** |

**Counts:** 42 changes total — **35 ambiguity-pins**, **7 mismatch-revisions**.

## Changes

- §2.1 Authentication — insert — ambiguity — a blank/whitespace-only `X-User-ID` counts as absent (`ERR_UNAUTHENTICATED`), and role validity is checked before the per-endpoint allow-list — guards.py:27-32
- §2.2 Envelope — revise — mismatch — `api_request_id` is `req_` + 20 uppercase alphanumerics, and `api_request_timestamp` is the *logical* clock, not wall time — envelope.py:51-55
- §2.3 Collections — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; unknown enum filter value → 400 while unknown id filter value → the entity's 404; undeclared query params ignored; nested parent path resolved before pagination validation — guards.py:158-195
- §2.4 Common fields — insert — ambiguity — `version` increments at most once per request and only if a field actually changed; a no-op write leaves `version` and `updated_at` untouched — store.py:127-147
- §2.4 Clock — revise — mismatch — accepts any parseable ISO instant including earlier ones; missing/unparseable → `ERR_INVALID_REQUEST`; returns 200 with `current_utc` as the sole data field; three cascade effects run in the stated order including misrepresentation-case closing — routes_notice.py:923-941
- §2.8 Numbers — insert — ambiguity — rounded values with a zero fraction serialise as JSON integers, not decimals — calc.py:23-27
- §2.10 Posture — insert — ambiguity — the recomputed score is written on every recomputation even when no declared transition applies; gate flags refresh before the transition lookup — services.py:299-321
- §2.11 Derived fields — insert — ambiguity — `available_content_count` never drops below 0 — services.py:456
- §3.1 Agent draft — insert — ambiguity — all five draft fields are required non-empty strings — routes_core.py:187-191
- §3.1 Agent submit — insert — ambiguity — the non-empty re-check failure at submit is `ERR_INVALID_REQUEST` — routes_core.py:230
- §3.1 Agent register — insert — ambiguity — an omitted receipt leaves any previously stored receipt unchanged — routes_core.py:273-275
- §3.1 Policy thresholds — insert — ambiguity — threshold points are plain integers with no upper bound — routes_core.py:309-320
- §3.1 Policy resolution — insert — ambiguity — built-in `POLICY_DEFAULTS` apply when no revision is `PUBLISHED` — services.py:16-24
- §3.1 Policy publish — insert — ambiguity — check order is `DRAFT` state → threshold ordering (400) → `expected_provider_version` — routes_core.py:357-369
- §3.2 Strike summary — insert — ambiguity — summary points are recomputed at read time and persist nothing — routes_core.py:492-513
- §3.3 Enroll — insert — ambiguity — empty `contact_email` → 400; an already-`ENROLLED` holder is an idempotent no-op — routes_core.py:689-694
- §3.3 Promote — insert — ambiguity — the active-reference-file check sits between the enrollment check and the abuse-score check; an already-`TRUSTED` holder is a no-op — routes_core.py:705-718
- §3.3 Suspend — insert — ambiguity — suspension from `PROSPECT` is allowed; an already-`SUSPENDED` holder is a no-op — routes_core.py:728-730
- §3.3 Quarantine — insert — ambiguity — the cascade touches only `DISABLED`/`COUNTER_NOTICED` items and leaves `RESTORATION_SCHEDULED` ones alone — services.py:525-529
- §3.4 Audit — revise — mismatch — the safe-harbour gate is satisfied when *any* provider is `ELIGIBLE`, not the requester's own — services.py:178-186
- §3.5 Batch — revise — mismatch — notice creation increments the batch's `notices_created`, and batch state is not a precondition — routes_notice.py:117-121
- §3.5 Provider attribution — insert — ambiguity — provider-of-notice resolution chain, ending in a single-provider whole-store fallback — services.py:119-137
- §3.5 Withdraw — revise — mismatch — an upheld child claim yields `ERR_INVALID_NOTICE_STATE`; claims processed in ascending `created_at`; all non-terminal counter-notices become `SUPERSEDED`; `restored_at` is stamped — services.py:427-447
- §3.5 Withdraw — revise — mismatch — withdrawing a `RECEIVED` (not yet validated) notice is also refused — routes_notice.py:301-302
- §3.6 URL resolution — insert — ambiguity — claimed URLs resolve only against the notice's own provider's material — routes_notice.py:187-204
- §3.6 Claim creation — insert — ambiguity — duplicate identical URLs produce one claim yet still count as matched — routes_notice.py:250-252
- §3.6 Claim creation — insert — ambiguity — `matched_claim_count` is counted before the duplicate-interval filter — routes_notice.py:281-287
- §3.7 Counter receipt — revise — mismatch — three ordered gates: claim must be `DISABLED`/`COUNTER_NOTICED` (`ERR_INVALID_CLAIM_STATE`), then the window, then account termination — routes_notice.py:496-504
- §3.7 Supersession — insert — ambiguity — supersession also reverts the item's dispute status `COUNTER_NOTICED → UNDER_NOTICE` — routes_notice.py:532-536
- §3.7 Forward — insert — ambiguity — a missing complainant email yields `ERR_INVALID_REQUEST`, checked after the state gate — routes_notice.py:612-619
- §3.7 Restoration — insert — ambiguity — "governing" counter-notice defined; `FORWARDED` also reaches `RESTORED`; a purged item keeps its access state while dispute still resolves — services.py:106-116
- §3.7 Uphold — insert — ambiguity — a live counter-notice yields `ERR_INVALID_CLAIM_STATE`, checked before the window check — routes_notice.py:394-407
- §3.8 Decay — insert — ambiguity — every clock advance rewrites `effective_points`, and expiry is tested before decay — services.py:543-554
- §3.8 Execute — insert — ambiguity — a strike-point shortfall at execution is `ERR_INVALID_ACCOUNT_STANDING` (409) — routes_notice.py:694-700
- §3.8 Case opening — insert — ambiguity — skipped when standing is already `TERMINATED`; fires from `ACTIVE` or `LIMITED` alike — services.py:342-377
- §3.8 Reinstatement — insert — ambiguity — writes the recomputed total back into the account's `strike_points` — routes_core.py:530-536
- §3.9 Auto-open — insert — ambiguity — the auto-opened case's `allegation` is `SYSTEM_ABUSE_SCORE_THRESHOLD` — services.py:492
- §3.9 Substantiate — insert — ambiguity — check order is `OPEN` state → upheld-claim precondition → separation of duties — routes_notice.py:853-862
- §3.9 Audit — insert — ambiguity — notices are attributed to a provider via the §3.5 resolution rule — services.py:238-246
- §3.9 Audit — insert — ambiguity — overdue counter-notices are attributed through their claim's `account_id` — services.py:249-259
- §3.9 Audit — insert — ambiguity — on a hard-gate failure the four raw measurements are still recorded as observed — services.py:299-313
- §3.9 Step-down — insert — ambiguity — a `STANDARD` holder stays `STANDARD`; an already-`SUSPENDED` holder keeps that status and runs no fresh quarantine cascade — routes_notice.py:897-900

Deliberately left unpinned (not observable through the API, so pinning would have added prose without removing ambiguity): enum-filter vs pagination validation ordering (both surface the same 400), the unreachable stored-fingerprint revalidation on reference activation, and the frozen reference-candidate set that cannot alter selection. PRD §4 (endpoint/role table) and §5 (error catalogue) were verified line-by-line against both route modules and `errors.CATALOG` and needed no change; the app-level `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` fallbacks lie outside the declared endpoint surface and were left out.
