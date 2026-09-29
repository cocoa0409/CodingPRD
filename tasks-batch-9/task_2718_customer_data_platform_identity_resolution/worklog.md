# Worklog — task_2718_customer_data_platform_identity_resolution

## Step 1: Create task directory — 2026-09-04T11:16:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2718_customer_data_platform_identity_resolution` and `.../workspace` (pre-assigned path, index fixed by scenario number 2718; no index auto-allocation performed).

## Step 2: Generate Scaffold — 2026-09-04T13:11:00.000Z

All three scaffold artifacts for task 2718 are complete and lint-clean.

## Files

| File | Lines | Top-level key(s) |
|---|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2718_customer_data_platform_identity_resolution/SCAFFOLD.yaml` | 3910 | `scenario`, `domain_name`, `api_prefix`, `response_envelope`, `complexity_profile`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` (§1.0–§1.7; neither design key present) |
| `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2748 | `scaffold_difficulty_design` only (§1.8) |
| `.../SCAFFOLD_CORNER_DESIGN.yaml` | 6971 | `scaffold_corner_design` only (§1.9) |

## Contents

**§1.0–§1.7** (`api_prefix: /cdp`, `difficulty_level: beyond_expert`, topology `graph`, shape `cyclic`, role model `segregation_of_duties`, layers `optimistic_concurrency` / `cascading_side_effects` / `dual_variant_calculation` / `rate_threshold_triggers`, consistency `immediate`): 13 entities, 12 state machines, 3 OCC rules, 12 calculations, 51 ordered validations, 57 endpoints, 51 errors, 7 roles. `scenario` stores the delegated text byte-verbatim (it had been stored as a wrapped block scalar; rewritten as a single-line scalar and re-verified equal).

**§1.8 — 9 difficulty rules × 2 instances = 18**: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.

**§1.9 — 9 sections, 113 instances (88 full test recipes + 25 `excluded_because` stubs)**: entities 13, state_machines 19, calculations 14, validations 9, endpoints 6, errors 37, rbac 5, cross_cutting_complexity_layers 9, consistency_model 1.

## Verification
- `scaffold_lint.py` → `VERDICT: clean lint` (57 endpoints, 13 entities, 18 §1.8 + 88 §1.9 instances, 831 calls).
- All three files parse with `yaml.safe_load`; all 113 + 18 instance names unique across both design files; every stub cites an existing §1.8 instance; **all 51 catalog errors are referenced** (each either triggered by a real recipe or stubbed against the §1.8 instance that triggers it).

## Two SCAFFOLD.yaml defects found and fixed while grounding §1.9
1. The Activation machine was missing five reachable transitions (`DISPATCHED→PAUSED`, `UNDERPERFORMING→PAUSED`, `DISPATCHED→TERMINATED`, `UNDERPERFORMING→TERMINATED`, `DRAFT→TERMINATED`) that the pause endpoint's own precondition and the retire cascade both require; added with matching side effects.
2. `ERR_ACTIVATION_CONCURRENCY_EXCEEDED` (priority 47) was unreachable because priority 46 forbade *any* window overlap on a destination, making `max_concurrent_activations` dead. Priority 46 is now scoped to **disjoint** windows only (closed-interval gap >= `cooldown_minutes`), with the §1.6 condition and the `cooldown_minutes` field description updated to match.

## Step 3: Copy shared files — 2026-09-04T13:11:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T13:30:00.000Z

PRD generation complete.

**Output:** `.../workspace/PRD.md` — **517 lines**, built incrementally (one `Write` + eight heredoc appends), ending at a completed §5 Error Code Catalogue table with no audit footer. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced; the scaffold's difficulty instruction text does not appear (`"harder than expert"` -> 0 hits).

**Top-level sections**
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 11 domain-derived subsections: 2.1 User and Role-Based Access Control - 2.2 API Response Structure (verbatim fixed block) - 2.3 Pagination - 2.4 Resource Identity, Timestamps and the Logical Clock - 2.5 Numeric Precision, Rounding and Score Widths - 2.6 Optimistic Concurrency Control on Parent Versions - 2.7 Cascade Discipline - 2.8 The Validation Ladder - 2.9 Idempotency and Terminal-State Lockdown - 2.10 Privacy Precedence and Segregation of Duties - 2.11 The Hash Quota Ledger and Conserved Quantities
- `## 3. Business Logic & Workflows` — 11 pipeline-chronological subsections: 3.1 Retail Feeds and Their Data-Quality Contract - 3.2 Batch Submission, Scoring and the Requeue Loop - 3.3 Promotion: Resolving Records into the Profile Graph - 3.4 Match Rules, Candidate Links and Steward Adjudication - 3.5 Household Formation, Overflow Buckets and Manual Reconciliation - 3.6 Consent Capture and the Effective-Channel Election - 3.7 Suppression Windows, Do-Not-Sell and Legal Holds - 3.8 Segment Definition and Sensitive-Attribute Governance - 3.9 Destinations, Audience Resolution and the Activation Lifecycle - 3.10 Attribution and Overlap Measurement - 3.11 Erasure, Downstream Verification and Retention Sweeps
- `## 4. Endpoint Definitions` — 4-column table, 57 rows (verified every row has exactly 4 columns); "All roles" defined in the intro paragraph by naming all seven roles
- `## 5. Error Code Catalogue` — 2-column table, 51 rows

**Coverage:** 13/13 entities - 57/57 endpoints - 51/51 errors (all 51 also referenced in §2/§3 prose, not only in the §5 table) - 51/51 validations (full priority ladder in §2.8 plus per-rule prose in §3) - 12/12 calculations (every constant embedded: DQ weights, MALFORMED_PENALTY 0.10, DQ_RECORD_MIN 0.60, DQ_MIN_SAMPLE 5, confidence weights, MAX_RETRY_ROUNDS 2, HOUSEHOLD_MAX_MEMBERS 6, pinned rounding order) - 12/12 state machines (every `from`/`to` state name present; verified mechanically against the scaffold) - 7/7 roles by exact spelling.

**Hard Contract reports**
1. **Field-Name Coverage — PASS.** Mechanical diff of the 169-name required union (146 entity fields U 88 path/body/query identifiers) against every backticked token in PRD.md: 0 missing, confirmed on two independent passes. A second 61-name check of nested-object and computed-read output identifiers also returned 0 missing.
2. **Rule Coverage — PASS.** All three OCC rules stated with write operation, required non-optional field, parent entity, exact error ID and 412; every cascade chain rendered hop-by-hop; both error-with-side-effect paths documented; all nine sibling-branch pairs given symmetric treatment; all field defaults/types/ranges stated.
3. **§3 Path Purity — PASS.** Scan of all 1,232 backticked tokens inside §3: zero tokens beginning with `/`, zero bare HTTP methods, zero method+path combinations.

Also verified: no pseudocode operators anywhere in §3, and no fuzzy quantifiers anywhere in the document.

**Orchestrator truncation check:** `tail -25` shows the file ending on the final `ERR_RETRY_LIMIT_REACHED | 409` table row — a real section boundary, not mid-sentence. All five `##` headings present. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-04T14:15:00.000Z

The implementation is complete, compiles cleanly, and passed an end-to-end smoke test. The smoke server (PID 1806134, port 41787) was killed by PID; port 41787 is free. `__pycache__` dirs removed.

## Files (4,336 lines total)
Root: `.../workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install`, then `exec python3 app.py` |
| `requirements.txt` | 1 | Flask 3.1.3 |
| `app.py` | 88 | app factory, blueprint registration, `before_request` auth, ApiError/400/404/405/HTTPException/catch-all handlers |
| `db.py` | 155 | in-memory `store`, `_seq` counter, logical clock (`CLOCK_EPOCH` = 2026-08-01T00:00:00Z), `new_entity/touch/paginate` |
| `errors.py` | 71 | `ERROR_CATALOG` (51 codes) + `ApiError` |
| `response.py` | 65 | envelope builders, pagination constants (default 10, max 100) |
| `middleware.py` | 68 | 7 roles, `load_actor/require_role/require_destination_actor` |
| `validators.py` | 275 | shape/type/range/enum validators (ladder rungs 1-6) |
| `services/calc.py` | 273 | Decimal ROUND_HALF_UP money/rates, DQ scoring, match confidence |
| `services/derive.py` | 409 | consent resolution, engagement score, segment predicates, derived-on-read counters |
| `services/ingest.py` | 354 | validate/requeue/promote, profile+household materialisation, link confirm/reject |
| `services/privacy.py` | 230 | suppression windows, legal holds, deletion requests, vendor task ack |
| `services/cascade.py` | 311 | up-to-3-hop cascades, audience resolution, segment retirement |
| `services/activation.py` | 206 | dispatch/pause/resume/report, performance + overlap reports |
| `services/retention.py` | 124 | retention run (expiry sweep, task timeouts, quota reset last) |
| `services/serialize.py` | 315 | per-collection response shaping |
| `routes/common.py` | 157 | fetch-or-404 helpers, OCC check, list/filter/sort plumbing |
| `routes/system.py` | 27 | clock set + retention run |
| `routes/sources.py` | 206 | 10 endpoints (source systems, ingest batches) |
| `routes/graph.py` | 325 | 13 endpoints (profiles, households, match rules, identity links) |
| `routes/consent.py` | 154 | 8 endpoints (consent records, suppression entries) |
| `routes/audience.py` | 409 | 18 endpoints (segments, destinations, activations) |
| `routes/erasure.py` | 114 | 6 endpoints (deletion requests, vendor deletion tasks) |

**57 `/cdp` endpoints** registered (verified against `app.url_map`), matching the PRD §4 table one-for-one. Storage is in-memory only; nothing is seeded at boot.

## Smoke test (58 assertions, all as expected)
201 create + 200 read + 400 `ERR_INVALID_REQUEST`; 409 `ERR_DUPLICATE_CODE`; 403 `ERR_UNAUTHORIZED`; 404 `ERR_SOURCE_SYSTEM_NOT_FOUND`; 401 `ERR_MISSING_AUTH_HEADERS`; batch validate->promote materialising 6 profiles + 1 household; `ERR_DETERMINISTIC_KEY_MISMATCH`, `ERR_INVALID_THRESHOLD_ORDER`, `ERR_CONFIDENCE_BELOW_FLOOR`, `ERR_SELF_LINK_FORBIDDEN`; link REJECT cascading the rule to DISABLED (min_precision breach); OCC 412 on both `expected_profile_version` and `expected_segment_version`; `ERR_FUTURE_CAPTURED_AT`, `ERR_SUPPRESSION_WINDOW_OVERLAP`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_DESTINATION_ACTOR_MISMATCH`, `ERR_MATCH_REPORT_EXCEEDS_DISPATCH`, `ERR_OVERLAP_SAME_SEGMENT`; dispatch deducting quota 1000->994; match report computing gross 0.3333 / net 0.4 / effective 0.3333 and flipping the activation to UNDERPERFORMING; pause->resume returning to ACTIVE; deletion propagate -> 1 vendor task -> ack -> request VERIFIED with the subject profile's PII redacted; clock set + retention run.

## PRD ambiguities and the choice made
1. `Profile.loyalty_tier` is "derived from the record's tier signal" but `IngestBatch.records` declares no tier field -> accept an optional `loyalty_tier` key per record, else `NONE`.
2. The three SENSITIVE profile attributes have no declared ingest channel -> accept optional same-named raw-record keys, else null.
3. `household-assignment` on a profile whose `address_hash` is null -> `ERR_INVALID_HOUSEHOLD_STATE`.
4. Segment retire: `SegmentAnalyst` may retire only `DRAFT`; `DataGovernanceOfficer` may retire `DRAFT`/`APPROVED`/`GOVERNANCE_EXPIRED`; analyst on the latter two gets `ERR_INVALID_STATE`.
5. Rung 31 `ERR_SENSITIVE_ATTRIBUTE_NOT_PERMITTED` is enforced at activation create, dispatch and resume.
6. `POST /cdp/retention-runs` returns 201 even though it creates no resource (per the §4 table).
7. `pair_evidence` similarity derivation for promote's probabilistic phase is spec-silent -> deterministic rule in `calc.pair_evidence`.
8. `address_hash` = sha256 hex of the lowercased, whitespace-collapsed `address_line`.
9. Filter query params are not enum-validated (e.g. `status=BOGUS` returns an empty page); only `limit`, `offset` and `attribution_basis` are, per §2.8.
10. Quota reset runs last in the retention run, so `remaining_daily_hash_quota == daily_hash_quota` after a new-day run.
11. On suppression release, blocked deletion requests are unblocked only when the released entry was a `LEGAL_HOLD` and no ACTIVE `LEGAL_HOLD` remains.
12. The feed-quarantine gate is re-evaluated after validate only, not after requeue.
13. Activation creation against a `RETIRED` segment -> `ERR_INVALID_STATE` (unstated).
14. Link-confirm on a `DELETION_PENDING`/`UNRESOLVED` profile -> `ERR_INVALID_STATE`; on `LEGAL_HOLD` -> `ERR_LEGAL_HOLD_ACTIVE` (the ladder is global, so rung 27 is honoured here too).
15. Re-assigning a profile to the household it already occupies still bumps both versions and is subject to the literal capacity guard.
16. `deletion_evidence_reference` has no declared bounds -> validated as a non-empty trimmed string.
17. Specific profile-state codes (22/26/27) are checked before the generic `ERR_INVALID_STATE` on link-confirm and deletion-request create, otherwise rung 22 would be unreachable (a MERGED_AWAY profile is also "not RESOLVED").
18. `meta.api_request_timestamp` uses wall clock ("server-generated", §2.2); all business timestamps use the logical clock.

## Step 5: Generate Unit Tests — 2026-09-04T14:30:00.000Z

Verification complete. Final state of the task-2718 test suite.

## Layout (both directories at the TASK ROOT, zero strays under `workspace/`)

**`test_helpers/` — 9 files, 2,607 lines**: `__init__.py` 2 | `api_client.py` 326 (57 endpoint methods, `PREFIX = "/cdp"`) | `api_errors.py` 133 (51 `ERR_*` constants + `set_error_http_status_map` at import) | `assertions.py` 343 (incl. `parse_instant`, the sub-second-width defence) | `constants.py` 186 | `factories.py` 326 (all money as JSON integers of cents) | `fixtures.py` 865 (69 builders across tiers 1-5) | `test_users.py` 103 | `types.py` 323

**`test_suite/` — 19 files, 8,216 lines (`conftest.py` 25 + 18 test modules, 8,191 lines), 147 tests**

| file | lines | tests |
|---|---|---|
| test_01_dual_variant_calc.py | 438 | 8 |
| test_02_combinatorial_formula.py | 343 | 8 |
| test_03_non_linear_state_machine.py | 349 | 7 |
| test_04_transitive_cascade.py | 370 | 6 |
| test_05_priority_pair_validation_conflict.py | 267 | 6 |
| test_06_boundary_precision_check.py | 369 | 7 |
| test_07_cross_entity_state_dependency.py | 315 | 6 |
| test_08_resource_temporal_overlap.py | 341 | 6 |
| test_09_compensating_invariant.py | 399 | 6 |
| test_10_entities.py | 604 | 12 |
| test_11_state_machines.py | 706 | 14 |
| test_12_calculations.py | 1037 | 11 |
| test_13_validations.py | 386 | 5 |
| test_14_endpoints.py | 443 | 6 |
| test_15_errors.py | 1099 | 28 |
| test_16_rbac.py | 281 | 5 |
| test_17_cross_cutting_complexity_layers.py | 323 | 5 |
| test_18_consistency_model.py | 121 | 1 |

## Design-index coverage

- **Queue A (§1.8 Difficulty): 18/18 non-stub instances -> 60 tests.** Zero skips.
- **Queue B (§1.9 Corner): 87/88 non-stub instances -> 87 tests (1:1).** 25 yaml stubs (`excluded_because`) correctly untranslated.
- 147 tests, 147 `Design:` tags, 105 distinct instances, **106 non-stub instances in the two indices** — the single gap is the one deliberate skip.

## Skipped instances

1. `Corner/entities/source_system_status_and_counters_are_system_owned_input_ignored` — **non-unique-derivability**. The PRD never states that a create body carrying server-owned fields is silently ignored rather than answering `ERR_INVALID_REQUEST`; both outcomes are consistent with the text, so no assertion is uniquely derivable.
2. 25 queue-B instances that the index itself marks `excluded_because` (stubs) — not translated by contract.

## Verification results (all clean)

- `py_compile` on all 28 helper + suite files: **COMPILE_OK**.
- `pytest --collect-only`: **147 tests collected, 0 errors**.
- Every test docstring: present, ends with exactly one `Design:` line as its **last** line, carries a quoted PRD citation, no ellipsis. 0 structural problems.
- 0 case-insensitive `scaffold` hits across `test_suite/` and `test_helpers/`.
- Static reference audit: 0 undefined helper symbols, 0 calls to non-existent `ApiClient` methods.
- 0 money-as-string occurrences.
- `__pycache__` / `.pytest_cache` removed; `find workspace` for test dirs returns nothing.
- `workspace/implementation/` never created, read, or modified; `worklog.md` never touched.

## Design-index-vs-PRD divergences resolved in the PRD's favour (flag for Step 7 / index owner)

1. Survivor identity is not uniquely derivable when one promotion mints both profiles (all three survivorship discriminators tie, `id` is forbidden as tie-breaker) — tests read `survivor_profile_id` off the response.
2. `consent_record_count` after three elections in one group is **1**, not the index's 3 (only rank one is `ACTIVE`).
3. The PRD never says the survivor adopts the loser's `household_id`; both sub-assertions dropped.
4. Rejection **clears** `submitted_by_user_id` (§3.8), contradicting the index.
5. `second_link_over_same_profile_pair_rejected` needs `min_precision=0.0`, else the rejection drives precision to 0.0000, disables the rule, and the closing 201 is unreachable.
6. `active_activation_count` immediately after activation *create* is self-contradictory in the PRD (line 130 vs 315/343); sub-assertion omitted, and the post-*dispatch* value 1 is asserted in `test_18` instead.
7. `deletion_ack_sla_hours` computed from the destination's own field rather than hard-coded to 72.
8. Two recipes had unreachable preconditions and were rebuilt via `fx.propagating_erasure(api, member_count=2)` and post-promotion rule declaration.

## Step 7: Run Tests and Iterate — 2026-09-04T15:01:00.000Z

Clean 8-round sweep achieved. Final report:

## Summary

**Iterations run:** 2 (iteration 1: 142/147 in every round, 6 distinct tests in the failure union; iteration 2: **147/147 passed in all 8 parallel rounds**).

**Tests deleted:** none. Two assertions were removed under STEP 1c partial-coverage handling (both id-derived expectations the PRD does not uniquely determine — details below); no test was skipped, xfailed, or downgraded from an `error_id` check.

**Fixes applied to `test_helpers/`**
- `test_helpers/assertions.py` -> `assert_created_at_ascending`: dropped the secondary `id`-ascending key, now asserts only `created_at` ascending. §2.3's tie-break sentence gives its own rationale as "so that the profiles minted by a single promotion appear in the record processing order described in §3.3" — a server-minted UUID (§2.4, "carries no type prefix and is never supplied by the client") carries no ordering, so `id` ascending and record-processing order are two divergent readings of one sentence and cannot both be implemented. The rest of the suite (test_02, test_06, test_14, test_15 household-overflow and link tests) depends on the processing-order reading, so the id tie-break was the un-derivable half. *(This was the flaky `test_10_entities.py::test_list_profiles_pagination_reports_total_count_and_has_more`, failing in 5/8 rounds purely on UUID luck.)*

**Fixes applied to `test_suite/`**
- `test_09_compensating_invariant.py::test_confirmed_merge_conserves_the_visible_lifetime_value_total`: was asserting the survivor is the profile that sorts first by `(created_at, id)`. Both endpoints are minted by one promotion at one logical instant, so all three §3.4 discriminators tie, and the PRD says outright "The profile's `id` is never consulted as a tie-breaker" — PRD determines no winner. Survivor/loser are now bound from `decided["survivor_profile_id"]`; every conservation assertion is retained. *(Flaky: failed 3/8 rounds.)*
- `test_11_state_machines.py::test_consent_opt_out_capture_pauses_delivering_activation`: consent capture was issued with the `DataEngineer` header. §3.6 "Only a `PrivacyOfficer` may capture a consent election" and the §4 table both name `PrivacyOfficer`, so the 403 was correct — switched to `PRIVACY`.
- `test_15_errors.py::test_deterministic_rule_without_key_rejected`: `f.deterministic_rule_payload("EMAIL_NORM", deterministic_key=None)` raised `TypeError` (positional + keyword collision). Now `f.deterministic_rule_payload(deterministic_key=None)`, which is the deterministic-rule-with-null-key case the test intends.
- `test_15_errors.py::test_ingest_batch_against_quarantined_source_rejected`: the reinstatement happened at the same logical instant the counted batch was created, where §3.1's mechanical definition ("`created_at` is at or after `dq_window_start_at`") keeps the batch in-window while the same paragraph's conclusion ("the in-window batch set is empty, so ... fall back to 0") requires it out. The clock is now advanced to `2026-08-03T00:00:00Z` before the reinstate so the reset is strictly later than the batch, and the two instant assertions were retargeted to that instant. No assertion was weakened, and `test_12_calculations.py::test_dq_pass_rate_reset_by_reinstate_excludes_prior_batches` already covered the same rule this way.

**Fixes applied to `implementation/`**
- `workspace/implementation/services/derive.py` -> `_gte`: the numeric-type guards tested only `(int, float)`, but `attribute_value` returns `channel_engagement_score` as a `Decimal` (from `engagement_score`), so every `channel_engagement_score GTE ...` predicate fell through to the string branch and matched nothing — a segment on that attribute silently had `member_count` 0. `Decimal` added to both guards. Real defect against §3.8 "`GTE` holds when the attribute is non-null and at least the predicate value, numerically — it applies to `lifetime_value_cents` and `channel_engagement_score`". *(This was the deterministic `test_12_calculations.py::test_overlap_jaccard_index_rounds_to_four_decimals` failure.)*

`worklog.md` was not touched by the subagent.

**Orchestrator verification:** independently read all 8 `results.$i.json` (mtime 14:50) — every round reports `passed == total == 147`. Artifacts present, not a phantom clean sweep.

## Step 8: Finalize PRD — 2026-09-04T15:10:00.000Z

Done. `PRD_FINALIZED.md` written with 4 edits.

## Size

| | PRD.md | PRD_FINALIZED.md | delta |
|---|---|---|---|
| lines | 517 | 517 | 0 (+0.00%) — every edit lands inside an existing paragraph line |
| bytes | 120,893 | 122,385 | +1,492 (+1.23%) |

## Changes

- **§2.3 (profiles/links/suppressions/activations/tasks bullet)** — revise — the secondary list key changes from "`id` ascending" to the platform's monotonic persistence/creation sequence, with an explicit statement that `id` is a tie-breaker on no list endpoint — `implementation/db.py:137-139` (`by_seq`), `routes/common.py:152-157` (`seq_sort`, `seq_sort_desc`)
- **§2.3 (households bullet)** — revise — "`created_at` ascending and `id` ascending across addresses" becomes "`created_at` ascending and persistence order", plus one sentence noting that at a single address creation order *is* `sequence_no` order, so one comparison satisfies both halves of the sentence — `routes/graph.py:129-133`, `services/derive.py:255-273`
- **§3.1 (reinstatement)** — revise — the flat conclusion "the in-window batch set is empty, so ... fall back to 0" becomes a statement that the mechanical at-or-after test is unchanged, that batches strictly before the reset drop out, and that a counted batch whose `created_at` equals the new `dq_window_start_at` exactly stays in-window and keeps contributing — `services/derive.py:281-292`, `routes/sources.py:83-86`
- **§3.4 (confirm branch, survivorship)** — insert — a fourth, last-resort discriminator after the three PRD ones: the profile persisted first survives (for one promotion, the profile minted from the earlier-processed record); also states that link endpoint position never influences survivorship. The existing "`id` is never consulted" sentence is preserved verbatim inside the revised sentence — `services/cascade.py:153-162`, `services/ingest.py:200-216`

## Per-edit pre-edit search log

**Edit 1 — §2.3 profiles bullet**
(a) Subject: the secondary ordering key applied to list endpoints.
(b) Enumerated: `db.by_seq`, `routes/common.py:collection_list/seq_sort/seq_sort_desc`, and all 14 list route registrations — `routes/sources.py:70` (source_systems, **descending**), `:166`, `routes/graph.py:38`, `:129`, `:182`, `:284`, `routes/consent.py:79` (consent_records, `(precedence_rank, created_at, _seq)`), `:129`, `routes/audience.py:88`, `:224`, `:325`, `routes/erasure.py:55`, `:92`. Also `test_helpers/assertions.py:152` and `test_suite/test_10_entities.py:191`.
(c) Adjustment: the universal claim was narrowed to *"`id` is not a tie-breaker"* rather than *"persistence order is always the second key"*, because the source-systems list is `created_at` **descending** with `_seq` still ascending, and consent-records puts `precedence_rank` ahead of both.

**Edit 2 — §2.3 households bullet**
(a) Subject: household list ordering, and whether the `sequence_no`-within-address clause and the cross-address clause can both hold under one comparator.
(b) Enumerated: `routes/graph.py:129-133`, `services/derive.py:255-273` (`assign_household`), `:236-254` (waterfall bucket scan), `services/cascade.py:227-238`, `services/derive.py:222-235`.
(c) Adjustment: kept both clauses and added a reconciling sentence — creation order *is* bucket order because `sequence_no` is strictly monotone per address.

**Edit 3 — §3.1 reinstatement**
(a) Subject: the in-window batch set boundary at `dq_window_start_at`, and the three derived DQ figures.
(b) Enumerated: `services/derive.py:278-292`, `:295-299`, `:302-306`, `services/serialize.py:15-31`, `routes/sources.py:54-55`, `:77-87`, `services/ingest.py:27-31`.
(c) Adjustment: did **not** write "reinstatement resets the totals to 0"; re-scoped to restate the mechanical at-or-after test as authoritative and demote the "empty set / 0" outcome to the ordinary case with the equal-instant boundary named as the exception.

**Edit 4 — §3.4 survivorship**
(a) Subject: which of two merging profiles survives when the three declared discriminators tie.
(b) Enumerated: `services/cascade.py:153-162` (`_survivor_rank`), `:176-239` (`merge_profiles`), and all three confirmation entry points — `services/ingest.py:200-216`, `routes/graph.py:324`, `:271`, `services/ingest.py:311`. Also `services/ingest.py:230-268` and `services/cascade.py:165-173` (`_reelect_primary_source`, deliberately untouched).
(c) Adjustment: two. Described the tie-break as "the profile the platform persisted first" rather than anything derived from the link's `left`/`right` fields; added the explicit "link endpoint never influences survivorship" clause.

No PRD edit was made for three Step 7 items, all confirmed already uniquely determined: the `test_11` consent-capture role (`routes/consent.py:23`), the `test_15` `deterministic_rule_payload` `TypeError` (pure factory-call bug), and the `derive.py::_gte` `Decimal` guard (real impl defect repaired against §3.8's already-explicit numeric wording).

## Step 9: Complete PRD — 2026-09-04T16:05:00.000Z

Run as **three sequential file-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 did the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were explicitly forbidden to copy over it). Orchestrator decision, recorded here per the autonomy clause: a single-pass scan of a 4,336-line implementation against a 517-line PRD reliably degenerates into a near-no-op copy, so the implementation was partitioned by module — pass 1 global plumbing, pass 2 ingestion/identity-graph, pass 3 privacy/audience/erasure.

### Pass 1 — core/global (app, db, errors, response, middleware, validators, routes/common, routes/system, services/serialize)
517 lines / 122,385 chars -> 526 lines / 131,739 chars (+9,309). **15 ambiguity-pins, 2 mismatch-revisions** across 14 regions. Highlights: auth precedes routing (401 on unrouted paths), header trimming, `OPTIONS` bypass; **mismatch** — the destination-actor check runs *after* path resource lookup, so unknown ids answer 404 not 403; `api_request_id` grammar (`req_` + 20 upper-alphanumerics) and wall-clock `api_request_timestamp`; envelope key insertion order; declared fields always present as `null` except omitted ingest-record optionals; framework error ids outside the §5 catalogue (`ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL`); `limit`/`offset` refused not clamped, integer-literal grammar, first-occurrence-wins on repeats; `has_more` formula; filter->sort->paginate with non-enum-validated filter values; timestamp emission truncated (not rounded) to 3 digits over microsecond storage; accepted timestamp grammar; shortest-exact numeric rendering; **mismatch** — rungs 15/17 precede rung 3 on the two destination-actor endpoints; JSON-object body requirement and trimmed-value persistence; retention run 201 vs clock-set 200.

### Pass 2 — ingestion/graph (routes/sources, routes/graph, services/ingest, services/calc, services/derive)
A first pass-2 attempt crashed on an API error after landing ~7.8k chars (528 lines / 139,515 chars); it was **resumed, not restarted** — the resume agent inventoried the already-pinned subjects (DQ scoring modes and rounding order, malformed penalty, quarantine gate and 5-record sample floor, requeue loop and retry ceiling of 2, promotion phase ordering, `(event_timestamp, external_id)` record order, deterministic-ambiguity handling, evidence derivation, probabilistic auto-confirm) and skipped them. Resume run: 528 lines / 139,515 -> 528 lines / 149,409 chars (+9,894, zero line growth). **11 ambiguity-pins, 6 mismatch-revisions.** Highlights: feed `REGISTERED`->`ACTIVE` unconditional on any successful promotion; feed list newest-first; identifier pre-checks trim before testing; phase-two link endpoint roles fixed (`left` = record's profile); phase three writes `RESOLVED` with **no** version bump and derives channel/consent counts at read time; phase four groups every touched profile with an `address_hash`; consent materialisation inside phase one with the new record exempt from the re-rank bump, plus flat version accounting; auto-confirmed link emitted at `version` 1 and non-mergeable pairs fall through silently to `PROPOSED`; evidence-key parse at rung 4 with the 0/0.5/1 value set; confirm-branch error triad is condition-major; survivor household re-homing on merge (absent from PRD entirely); reject-branch precision derivation with `1.0000` on a zero denominator; household aggregates derived per read with alphabetical `dominant_last_name` tie-break; manual-override guard order (state before capacity, no self-allowance, same-household no-op still bumps both versions); waterfall `sequence_no` = max over buckets in any status + 1; a `MERGED_AWAY` profile reports every channel `OPT_OUT`; full consent-state read shape.

### Pass 3 — privacy/audience/erasure (routes/consent, routes/audience, routes/erasure, services/privacy, services/cascade, services/activation, services/retention)
528 lines / 149,409 -> 530 lines / 178,032 chars (+28,623; one new paragraph inside §3.9, no new sections). **16 ambiguity-pins, 31 mismatch-revisions** — 47 edits. Highlights: quota refunds use stored `dispatched_hash_count` and are never clamped, so quota may exceed `daily_hash_quota`; the canonical **audience sweep** paragraph (six call sites, unfiltered, three counts, `dispatched_hash_count` untouched, `updated_at` restamped without a version bump) replacing the PRD's channel-filtered reading; `privacy_status` derives from entry status alone, never the window; release unblocking keyed on hold count rather than a return to `NORMAL`; expiry never unblocks, leaving `BLOCKED_LEGAL_HOLD` stuck; `GTE` lexicographic on strings and type-family-bound; `member_count` / `active_activation_count` / `underperforming_activation_count` all derived at read time and never written by retirement; activation creation refuses only `RETIRED` with a seven-test order; dispatch checks destination before governance and treats null/expired approval as `ERR_GOVERNANCE_NOT_APPROVED`; a refused gate commits none of the four counts; match reports **replace** the two vendor counts and credit conversions naming `MERGED_AWAY`/`DELETED` profiles; resume always lands `ACTIVE` and leaves all three rates untouched; overlap `other_segment_id` empty -> `ERR_SEGMENT_NOT_FOUND`; erasure `MERGED_AWAY`/`DELETED` judged ahead of both `ERR_INVALID_STATE` tests (inverting rungs 21/22); minted suppression `reason_code` literal `PRIVACY_DELETE`; a minted vendor task is first readable at `version` **2** (`PENDING` never observable); `FAILED` not directly re-acknowledgeable; all-resolved-with-a-failure stays `PROPAGATING` and `PARTIALLY_VERIFIED` only arrives from retention step three; expiring election's `precedence_rank` forced to 0; an audience sweep runs between retention steps two and three; quota reset runs last and overwrites refunds; a deletion retry mints nothing at all.

### Final orchestrator verification
- `PRD.md` 517 lines / 120,893 chars -> `PRD_FINALIZED.md` 517 / 122,385 -> `PRD_COMPLETED.md` **530 lines / 178,032 chars**.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` = **161 changed lines** — not byte-identical, so the scan demonstrably ran.
- `PRD_COMPLETED.md` ends on the final `ERR_RETRY_LIMIT_REACHED | 409` catalogue row (a real section boundary) and retains all five `##` sections.
- All 8 `results.$i.json` from the Step 7 clean sweep re-read: **147/147 in every round**. Step 9 touched no implementation or test file, so the sweep result stands.

**Pipeline complete.**
