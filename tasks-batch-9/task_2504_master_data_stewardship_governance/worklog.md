# Worklog — task_2504_master_data_stewardship_governance

## Step 1: Create task directory — 2026-09-03T02:42:06.413Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2504_master_data_stewardship_governance` and its `workspace/` subdirectory. Index 2504 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed (32 concurrent pipelines on this host would collide on auto-allocation).

## Step 2: Generate scaffold — 2026-09-03T04:32:34.633Z

Done. All three scaffold artifacts for task 2504 are written and the lint is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2504_master_data_stewardship_governance/`)
- `SCAFFOLD.yaml` — 2,603 lines, §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,234 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,193 lines, single key `scaffold_corner_design`

**Lint verdict (verbatim)**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2504_master_data_stewardship_governance/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2504_master_data_stewardship_governance/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2504_master_data_stewardship_governance/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  1163

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Worklog summary**

- Domain: `master-data-stewardship-governance`, api_prefix `/mdm`; archetypes compliance_audit / graph_constraint; entity_topology graph, state_machine_shape parallel, role_model segregation_of_duties, consistency_model immediate; complexity layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.
- §1.1 entities: 12 — Domain, SourceSystem, Steward, SourceRegistration, StewardAssignment, QualityRule, ScorecardRun (`common_fields: false`), QualityFinding, MasterRecord, MergeProposal, ChangeRequest, ConsumerSubscription. Four MDM subject domains modelled as `Domain.code` CUSTOMER|PRODUCT|VENDOR|LOCATION.
- §1.2 10 state machines + 2 OCC concurrency rules (both anchored on `expected_domain_version`); §1.3 8 calculations (scorecard PROVISIONAL/CERTIFIED, posture constraint-propagation, match score, survivorship score, impact lead time, freeze-window geometry, completeness, counter reconciliation); §1.4 15-rung validation ladder; §1.5 57 endpoints; §1.6 66 error ids; §1.7 5 roles (GovernanceAdmin, DataOwner, DataSteward, ConsumerRep, Auditor).
- §1.8 difficulty design: 9 rule blocks × 2 = **18 instances** (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- §1.9 corner design: **91 instances** (68 with full `test_recipe`, 23 `excluded_because` stubs citing §1.8) across all 9 claim-extraction-guide sections — entities 12, state_machines 15, calculations 12, validations 11, endpoints 5, errors 20, RBAC 10, complexity_layers 5, consistency_model 1.
- Verified beyond the lint: all 66 error ids are triggered by §1.8/§1.9; all 57 endpoints are exercised by at least one structured call; every query filter used is declared in §1.5; instance names unique across both design files; all `difficulty_instance` citations resolve; no forbidden concurrency vocabulary.
- One internal inconsistency found and fixed in SCAFFOLD.yaml during the audit: `list_conventions` prose said `limit` default 50 / max 200 while `response_envelope.pagination_defaults` said 10 / 100 — prose now reads default 10, min 1, max 100.

## Step 3: Copy shared files — 2026-09-03T04:32:34.633Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T04:43:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2504_master_data_stewardship_governance/workspace/PRD.md`.

## Structure (409 lines)

- **§1 Introduction** — 3 paragraphs (governance-office framing, the "gated not advisory" posture thesis, technical shape).
- **§2 Global Specifications** — 10 subsections, domain-derived titles: 2.1 Governance Identities and RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination and List Ordering · 2.4 Common Resource Properties and the Logical Clock · 2.5 Domain Version Anchoring and OCC · 2.6 Governance Posture — the Domain-Level Gate · 2.7 Pinned Evaluation Order, Precision and Rounding · 2.8 Conserved Governance Counters and Compensating Actions · 2.9 Path Resolution and Validation Precedence (the full 15-step priority ladder) · 2.10 Data Classification and Sensitive-Data Handling.
- **§3 Business Logic** — 9 subsections organised by governance lifecycle: 3.1 standing up a domain (registries → activation) · 3.2 authoritative-source designation + 5-hop decertification cascade + all 5 posture transitions · 3.3 quality rules and the 100-point weight budget · 3.4 scorecard runs (both variants, per-rule rounding, pinned multiplier, finding dedupe) · 3.5 finding remediation fork · 3.6 master record ingest/curate/publish (parallel dimensions) · 3.7 match scoring, review, 3-hop merge, both survivorship variants · 3.8 change control (impact assessment, approval routing, freeze-window geometry, 3-hop apply, withdrawal compensation) · 3.9 consumers, lineage, acknowledgement.
- **§4** — 4-column table, all 57 endpoints.
- **§5** — 2-column table, all 66 error ids.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 119 required, 119 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 32 required, 32 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose (explicit 1–15 ordered ladder in §2.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_domain_version + ERR_STALE_DOMAIN_VERSION/412 all named), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (incl. both variant pairs, all constants unit-embedded, all pinned rounding orders), 0 missing
- validations[] conditions: 66 error ids checked, 66 matchable to a condition in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 57 checked, 57 expressed, 0 missing
- entities[].fields[] structured content: 119 checked, 119 reconstructible from prose (defaults, enums, ranges, null-initial, common_fields:false on ScorecardRun), 0 missing
- sibling-branch symmetry: 13 groups checked, 13 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 938
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 diffs byte-for-byte clean against `section-2.2-response-structure.md`. No fuzzy/approximating words and no operator syntax anywhere in §2 or §3. No audit footer — the file ends at §5.

## Tail verification

Final line count: **409**. Last 3 lines verbatim:

```
| `ERR_DUPLICATE_CONSUMER_CODE` | 409 |
| `ERR_DUPLICATE_NATURAL_KEY` | 409 |
| `ERR_RULE_WEIGHT_BUDGET_EXCEEDED` | 422 |
```

That is the complete final row of the §5 error table (66/66 rows present, matching the scaffold's last entry `ERR_RULE_WEIGHT_BUDGET_EXCEEDED`), so the document ends at a real section boundary with no truncation. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened.

**Orchestrator anti-truncation verification (independent):** `wc -l` = 409, `wc -c` = 101125, `tail -6` ends with the complete table row `| \`ERR_RULE_WEIGHT_BUDGET_EXCEEDED\` | 422 |`, and `grep '^#'` shows a complete §1–§5 outline terminating at `## 5. Error Code Catalogue`. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T05:55:00.000Z

The test suite for task 2504 is complete and audited.

## Files written

**Infrastructure — `/home/ubuntu/github/CodingPRD/tasks/task_2504_master_data_stewardship_governance/test_helpers/`** (9 modules, imports cleanly, 193 exported names): `types.py` (25 enums + 12 TypedDicts), `api_client.py` (`ApiClient` with all 57 endpoint methods), `api_errors.py` (66-member `ApiErrorId` + registered HTTP status map), `constants.py`, `test_users.py` (identity-bound header factories), `factories.py`, `assertions.py`, `fixtures.py` (composite setup chains anchored on `setup_governed_domain`), `__init__.py`.

**Test cases — `.../test_suite/`**: `conftest.py` plus 17 numbered files, 190 test functions / **201 collected items** (one 12-way parametrized not-found sweep). Per-file counts run from 6 to 37; queue A occupies `test_01`–`test_09`, queue B occupies `test_10`–`test_17`.

## Coverage (machine-audited)

- **Queue A: 18/18 difficulty instances, every one with ≥2 tests** (range 3–6). Zero thin.
- **Queue B: 68/68 non-stub corner instances covered**, ≥1 test each.
- **23 stubs correctly not translated** — every `excluded_because:` pointer was verified to resolve to a real difficulty instance, and no stub name appears anywhere in the suite.
- **Tag hygiene: zero problems.** Every test carries exactly one `Design:` line, it is the last line of its docstring, and every tag resolves to a real non-stub instance.
- **Citations:** every quoted span of 25+ characters in all 190 docstrings is byte-verbatim in `PRD.md` (I fixed one, in `test_15`, where a quote had begun mid-way through the PRD's bold markers).
- **Forbidden constructs: none** — no `skip`/`xfail`, no mocking or patching, no direct HTTP or DB access, no sleeping, and no scaffold/design vocabulary leakage in either the tests or the helpers.

## Instances skipped

**None.** All 86 translatable instances passed the PRD-first filter. Six *individual assertions* inside otherwise-covered instances were dropped as not uniquely derivable, and these are the real PRD gaps worth surfacing:

1. `survivorship_variant`'s enum literals (`SOURCE_PRIORITY` / `SCORE_PRIORITY`) appear nowhere in the PRD — it names the variants only as prose. Dropped in three places; the merge outcome is instead pinned via `effective_survivor_master_record_id`, `survivor_swapped` and the loser's `MERGED_AWAY`.
2. Exact `created_at` / `updated_at` instants: the PRD never states these are clock-derived rather than wall-clock, so ISO-8601 validity is asserted instead of the literal `2026-08-01T00:00:00.000Z`.
3. Whether withdrawal clears `scheduled_apply_at`, and whether it retains `impact_consumer_count` / `required_lead_days` — the PRD's withdrawal paragraph is silent on both.
4. Whether a plain steward-assignment creation bumps `Domain.version` — the PRD states a version advance for a *handover* only, so two agents independently re-staged their OCC-staleness setups to use an operation the PRD explicitly says advances the version.
5. "No PATCH/DELETE endpoint exists for scorecard runs" — untestable without inventing an undeclared path.

## PRD-vs-index conflicts resolved PRD-first

Three defects in the design indices were adjudicated against the contract, consistently across all six translators: the index's `governance_posture == OPEN` for a freshly created domain is wrong (the PRD says a domain with no authoritative source is already `FROZEN`); `certification_level: "ASSOCIATE"` is not in the PRD enum and was substituted with `JUNIOR`; and `ERR_CHANGE_CALENDAR_CAPACITY` is 409, not the index's stated 422. One further case (`open_finding_weight_recounts_only_the_open_status_set`) had pre-computed literals that only hold at a 1.00 posture multiplier while its own recipe left the domain `FROZEN` — the setup was corrected to give the domain its certified authoritative source so the literals hold under the PRD, rather than recomputing them.

One coordination note: the six translators worked concurrently against shared `test_helpers/`, and three independently appended near-identical timestamp helpers. They converged on the surviving `assert_instant_equals`, and the final state imports and collects cleanly — but that shared-file contention is the thing to watch if this partitioning is reused.

## Step 6: Generate implementation — 2026-09-03T05:55:00.000Z

The implementation is complete and verified.

## What was delivered

**22 files** in `/home/ubuntu/github/CodingPRD/tasks/task_2504_master_data_stewardship_governance/workspace/implementation/` (~3,400 lines):

- `start.sh` (executable, `exec python3 app.py`, honours `PORT`, default 10000, binds `0.0.0.0`; installs Flask only if missing so the per-test reboot loop doesn't thrash pip), `requirements.txt`
- `app.py` — blueprint registration, `ApiError`/400/404/405/catch-all handlers, a global `threading.Lock` acquired in `before_request` and released in `teardown_request`
- Core: `util.py`, `errors.py`, `db.py`, `serialize.py`, `response.py`, `auth.py`, `validation.py`, `services.py`
- `routes/` — 13 blueprint modules, one per collection

**57 endpoints**, exactly matching PRD §4: domains 6, source-systems 5, stewards 3, source-registrations 3, steward-assignments 3, quality-rules 4, scorecard-runs 2, quality-findings 5, master-records 5, merge-proposals 6, change-requests 9, consumer-subscriptions 5, `/_clock/set_current_utc` 1.

## Verification performed

- Route table enumerated: 57 rules, correct methods/paths.
- Error catalogue diffed against PRD §5: 66 ids, zero missing, zero extra, zero HTTP-status mismatches.
- Two end-to-end smoke suites (~120 assertions) both pass: registry standup → certification → OCC-guarded registration/assignment (incl. a 412) → rule budget/PRINCIPAL rejections → activation → scorecard run and finding lifecycle → ingest/curate/publish → both survivorship variants (`SOURCE_PRIORITY` with swap, `SCORE_PRIORITY` with MEDIUM-confidence override and field-map provenance) → consumer registration, lineage, acknowledgement → full change-control path (impact assessment arithmetic, `ERR_LEAD_TIME_NOT_SATISFIED`, exact 72h freeze-window separation boundary, `ERR_CHANGE_CALENDAR_CAPACITY`, `ERR_TIER1_ACK_MISSING`, `ERR_APPLY_WINDOW_NOT_REACHED`, 3-hop apply with classification uplift and consumer suspension, withdrawal compensation) → 5-hop decertification cascade (revoked registration, posture FROZEN, retraction+quarantine, lineage staling, counter reconciliation) → auth/authorisation/404/400 paths.
- Three consecutive fresh boots: all 12 collections report `total_count: 0` and the clock reads `2026-08-01T00:00:00.000Z`. Grep confirms no `open()`, sqlite, pickle, json-dump or `/tmp` usage anywhere — storage is purely Python dicts.

## PRD ambiguities resolved

1. `created_at`/`updated_at`/`api_request_timestamp` all come from the logical clock; insertion sequence is the list-ordering tiebreak so ordering stays deterministic while the clock is frozen.
2. Certifying a source recomputes posture, but the posture formula never reads `SourceSystem.status`, so it is a no-op and does not bump `Domain.version`.
3. Decertify bumps `Domain.version` once for every domain that had a registration revoked.
4. Merge-decide order: proposal state → SoD → posture → both CURATED → effective survivor's source CERTIFIED → confidence.
5. Change-apply order follows §2.9 priorities: status (8) → posture (11) → clock (13) → TIER1 ack (14).
6. Steward-assignment: `ERR_INVALID_INTERVAL` precedes `ERR_ASSIGNMENT_OVERLAP`.
7. Schedule order: lead time → freeze conflict → calendar capacity.
8. Lineage order: `ERR_AUTHORITATIVE_SOURCE_UNDEFINED` → source mismatch → target mismatch → cycle.
9. "Acting `X-User-ID` must equal `requester_steward_id`/`reviewer_steward_id`" has no declared error id; mapped to `ERR_NOT_DOMAIN_OWNER`/`ERR_NOT_DOMAIN_STEWARD` by acting role, checked after state reachability.
10. QUARANTINED→CURATED: missing `last_verified_at` → 400; supplied but not strictly later → `ERR_INVALID_STATE_TRANSITION`.
11. Rescore with a candidate no longer CANDIDATE/CURATED → `ERR_INVALID_STATE_TRANSITION`.
12. `GET /mdm/domains/{id}/scorecard` defaults `basis` to PROVISIONAL, draws each rule's measurement from that rule's latest finding, and applies no certified-source gate (it is a pure read).
13. `survivorship_score` recency: staleness clamped at >=0, so a future `last_verified_at` earns the 20-point maximum.
14. `rework_note` (<10) and `waiver_justification` (<20) are schema violations at priority 4 -> 400; `override_justification` (<20) is `ERR_MATCH_CONFIDENCE_TOO_LOW` -> 422.
15. Percentage inputs range-checked 0..100 -> 400; `attributes` validated only as an object; "populated" means not `None` and not `""`.
16. `PATCH` a RETIRED rule to ACTIVE -> `ERR_INVALID_STATE_TRANSITION`; the weight budget is computed over the post-patch ACTIVE set.
17. Duplicate `rule_code` spans all rules of the domain regardless of status.
18. Consumer-subscription create: clearance check (12) runs before `ERR_DUPLICATE_CONSUMER_CODE` (14).
19. Re-documenting lineage on an already-DOCUMENTED subscription -> `ERR_INVALID_STATE_TRANSITION` (only UNDOCUMENTED and STALE are reachable sources).
20. `survivorship_field_map` key order = survivor's attribute keys in insertion order, then loser-only keys.
21. `pending_change_request_id` is a single slot: scheduling a second change re-points an already-notified consumer at the newer request, so withdrawing that newer request releases the slot entirely rather than restoring the older notification.
22. Apply's hop-2 suspension and final notification release clear `pending_change_request_id`/`notified_at`/`acknowledged_at` but deliberately preserve `acknowledged_revision` (the spec lists only the first three); withdrawal clears all four.

One incidental note: mid-session I ran a `pkill -f app.py`, which pattern-matched its own shell and aborted. Other tasks' servers named `app.py` were still alive immediately afterwards, but if a concurrent task reports a spuriously dead server around that moment, that is the likely cause. All subsequent cleanup was done by explicit PID.

**Orchestrator note on Step 5/6 isolation:** both agents were launched back-to-back with Step 6 starting before any `test_suite/` file existed (Step 5 spends its first minutes reading ~560 KB of yaml), and Step 6's prompt hard-forbade reading `test_suite/`, `test_helpers/`, and both design indices. Isolation held.

## Step 7: Run tests and iterate — 2026-09-03T05:47:00.000Z

The task artifact is already green. Verified rigorously rather than assumed.

## Summary

**Iterations run:** 1 (a single 8-round parallel stability sweep — no fixes were needed).

**Sweep integrity checks performed before accepting the result:**
- All 8 `results.{1..8}.json` exist, parse as JSON, and each carries a `total` field.
- All 8 files have fresh mtimes from this run (2026-09-03 05:45:49–05:45:50).
- No `Terminated` anywhere in `workspace/sweep.log` (0 matches) — the sweep was not reaped; it ran under `setsid nohup` as required.
- Per-round durations all ~355 s, consistent with `--isolation per-test-server` × 201 tests under 8× concurrent load.
- `skipped == 0` in every round, and a grep of `test_suite/` + `test_helpers/` found **no** `pytest.mark.skip` / `xfail` markers — nothing is passing by suppression.
- Computed the **union of non-passing tests across all 8 rounds** from the per-test `status` fields: **0 tests**. No flakiness signal (no test passed in one round and failed in another).

**Tests deleted:** none. No test failed in any round, so no test entered the STEP 1 coverage / unique-derivability audit.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Final sweep, per-round `passed`/`total` quoted from the results files:**

| Round | passed / total | failed | errors | skipped |
|---|---|---|---|---|
| 1 | 201 / 201 | 0 | 0 | 0 |
| 2 | 201 / 201 | 0 | 0 | 0 |
| 3 | 201 / 201 | 0 | 0 | 0 |
| 4 | 201 / 201 | 0 | 0 | 0 |
| 5 | 201 / 201 | 0 | 0 | 0 |
| 6 | 201 / 201 | 0 | 0 | 0 |
| 7 | 201 / 201 | 0 | 0 | 0 |
| 8 | 201 / 201 | 0 | 0 | 0 |

Notes for the caller: the implementation stores everything in plain Python dicts in `workspace/implementation/db.py` (`Store` starts empty on every boot — no seeding, no SQLite, no `/tmp` cache), so the per-test-server isolation genuinely wipes state between tests. `start.sh` already guards its `pip install` behind an `import flask` probe, which is why 8 concurrent rounds boot ~1600 servers without install contention — worth preserving if that file is ever touched.

**Orchestrator independent verification of the Step 7 sweep artifacts** (a Step 7 agent can claim a clean sweep without leaving evidence, so this was re-checked directly rather than trusted): `ls` shows 8 `results.*.json` all ~59.7 KB with mtime 05:45; a python `json.load` of each reports `passed=201 total=201 failed=0 errors=0 skipped=0`, `duration_seconds` 354.5–355.1; iterating each file's 201 per-test entries yields **0 non-passing** in all 8 rounds; `grep -c Terminated workspace/sweep.log` = 0 (not reaped); `grep -rn "mark.skip\|mark.xfail" test_suite/ test_helpers/` = 0 matches. The clean sweep is real.

## Step 8: Finalize PRD — 2026-09-03T05:47:00.000Z

**SKIPPED per the skill's skip condition.** Step 7 exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior Step 7 exercised, there is no `<step_7_diff>` to hand off, and no subagent was spawned. `PRD_FINALIZED.md` is intentionally absent; Step 9 will take `PRD.md` as its source.

## Step 9: Complete PRD — 2026-09-03T06:20:00.000Z (pass A of 3)

**Orchestrator decision (recorded per the AUTONOMY directive):** Step 9 was split into three sequential, implementation-file-partitioned passes rather than one monolithic scan. Rationale: `implementation/` is 3,403 lines across 23 modules with 57 endpoints; a single agent asked to walk all of it exhaustively predictably under-covers the tail of the walk, and the failure mode is silent (a PRD_COMPLETED.md that is byte-identical or near-identical to its source, i.e. the scan never really ran). Partitioning by impl file makes each pass's coverage obligation small enough to actually discharge, and sequencing them (rather than running them concurrently) is required because all three edit the same file. Pass A created PRD_COMPLETED.md from PRD.md (no PRD_FINALIZED.md exists — Step 8 was skipped) and owned foundations + cross-cutting §2.x + §3.1/§3.2; Pass B owned §3.3–§3.6; Pass C owned §3.7–§3.9. Each pass was told to hand forward, in its summary, anything it noticed outside its own partition, and the next pass's prompt carried those items as explicit must-resolve hand-offs.

### Pass A summary (verbatim)

Pass A complete.

## Line/char accounting
| | PRD.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 409 | 409 |
| chars | 101,125 | 108,885 |

Char delta **+7,760**; zero new lines (all edits are in-paragraph inserts/revisions — no new sections or paragraphs). 22 PRD lines touched, 26 distinct changes: **19 ambiguity-pins, 7 mismatch-revisions**. `implementation/`, `test_suite/`, `test_helpers/` untouched; all 8 `results.*.json` intact.

## Changes
- §2.1 — insert — ambiguity — an `X-User-Role`/`X-User-ID` header that is present but empty or whitespace-only counts as absent — `auth.py:24-33`
- §2.1 — insert — ambiguity — where an operation demands the acting `X-User-ID` *equal* a steward field on the target, the failure is the acting role's entitlement error (`ERR_NOT_DOMAIN_OWNER`/`ERR_NOT_DOMAIN_STEWARD`), not a dedicated id; *differ* stays `ERR_SEGREGATION_OF_DUTIES` — `auth.py:58-64`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + twenty uppercase letters/digits — `response.py:16-19`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock (not wall clock), on error envelopes too — `response.py:19`
- §2.3 — insert — ambiguity — `offset` min 0 / no maximum, over-large offset yields an empty page, non-integer either param → `ERR_INVALID_REQUEST`, empty value = omitted — `validation.py:177-197`
- §2.3 — insert — ambiguity — rows sharing a `created_at` are ordered by server creation sequence — `db.py:120`
- §2.4 — insert — ambiguity — `created_at` is stamped from the logical clock; `updated_at` and `version` always move together so a new row's `updated_at` equals its `created_at` — `db.py:59-75`
- §2.4 — insert — ambiguity — `to_iso8601` is required, any parseable instant is accepted (clock may be wound backwards), and the body carries `current_utc` alone — `routes/clock.py:20-24`
- §2.5 — insert — ambiguity — reads and failed requests never bump `version`; the bump is applied before serialisation so a domain-returning response already shows N+1 — `response.py:29-31`, `db.py:92-102`
- §2.5 — revise — **mismatch** — both version-checked creates always advance `Domain.version` by one on success, regardless of role and of whether any derived value moved — `source_registrations.py:67`, `steward_assignments.py:88`
- §2.6 — revise — **mismatch** — PRD's recompute-trigger list was under-inclusive; now names all triggers (run end, finding-set mutations, registration create/status change, activation, source certify/decertify, publication, `MERGE` decision, schedule/apply/withdraw-from-`SCHEDULED`), states it is one idempotent whole-table re-derivation of pointer+weight+posture+counters, at most once per domain per request, and that a no-move recompute does not itself bump `version` — `services.py:142-195` and all call sites
- §2.7 — revise — **mismatch** — "interval comparisons are inclusive" was a false universal; carved out the half-open accountability/registration intervals and workflow-declared strict inequalities (`due_at`) — `db.py:184-190`, `quality_findings.py:79`
- §2.9 step 5 — insert — ambiguity — multiple unresolvable body identifiers are checked in the order the step lists them (verified across all six creating endpoints) — `source_registrations.py:31-33`, `steward_assignments.py:39-40`, `quality_rules.py:42-43`, `master_records.py:29-30`, `merge_proposals.py:28-30`
- §3.1 — insert — ambiguity — `SourceSystem.code` uniqueness is exact-string; `name` must be >=1 char — `source_systems.py:22-28`
- §3.1 — revise — **mismatch** — "certification is the gate that lets a source become authoritative" was wrong: the posture test counts an `ACTIVE` `AUTHORITATIVE` registration on a merely `REGISTERED` system, and certification instead gates activation, `CERTIFIED` runs, curation and merge survivorship separately — `services.py:162`, `source_registrations.py:43`
- §3.1 — insert — ambiguity — certify takes no body; a domain's `version` advances on certification only if the recompute actually moved a derived value — `source_systems.py:62-76`, `services.py:193`
- §3.1 — insert — ambiguity — steward `email` uniqueness is exact-string / case-sensitive — `stewards.py:25-27`
- §3.1 — insert — ambiguity — `ERR_INVALID_INTERVAL` precedes the overlap test; overlap is per (domain, `steward_role`) ignoring `steward_id`; >=2 intersecting incumbents still yields `ERR_ASSIGNMENT_OVERLAP` even with `supersede_incumbent`; a no-op `supersede_incumbent` is accepted — `steward_assignments.py:46-69`
- §3.1 — revise — **mismatch** — `Domain.version` advances on *every* successful assignment creation, not only on handover — `steward_assignments.py:88`
- §3.1 — insert — ambiguity — activation's four readiness conditions are evaluated in the stated order, so the earlier unmet one wins — `domains.py:94-121`
- §3.2 — insert — ambiguity — `trust_rank` need not be unique in the domain; a supplied `effective_to` must be strictly after `effective_from` (`ERR_INVALID_INTERVAL`) — `source_registrations.py:26,39-40`
- §3.2 — insert — ambiguity — registration supersession is unconditional: no opt-in flag, no ordering relation between the two `effective_from`s — `source_registrations.py:43-62`
- §3.2 — revise — **mismatch** — hop 3 visits *every* domain holding a revoked registration whatever its role (only those losing authoritative go on to hops 4/5); hops 4/5 fire only when the posture actually *moves* into `FROZEN`; `version` +1 for every domain with a revoked registration — `source_systems.py:99-116`, `services.py:170-175`
- §3.2 — revise — **mismatch** — `OPEN → FROZEN` also fires on weight crossing 40.00 in one recompute (`authoritative_source_code` nulling scoped to the lost-registration case); `RESTRICTED → OPEN` is not limited to resolve/waive; added the missing `FROZEN → OPEN` one-step transition — `services.py:163-175`
- §3.4 (computed read only) — insert — ambiguity — `basis` defaults to `PROVISIONAL`; the stored measurement is the `measured_pct` of each `ACTIVE` rule's most recently created finding whatever its status, a finding-less rule supplying none; and the read is never gated on a certified authoritative source — `domains.py:130-147`, `services.py:248-256`
- §5 — insert — ambiguity — unrouted path → HTTP 404 and disallowed method → HTTP 405, both with `error_id` `ERR_INVALID_REQUEST` (outside the table's 400) — `app.py:52-60`

## Deliberately left to Pass B / Pass C
- **§3.6, line 222 — a real mismatch Pass B must fix.** `services._freeze_cascade` (`services.py:128-139`) quarantines **only** records whose `publication_status` is `PUBLISHED`. A `CURATED`-but-unpublished record in a freezing domain stays `CURATED`. PRD §3.6 currently reads as if hop 4 applies to any `CURATED` record and merely retracts "if it was published". §3.2's hop-4 wording is already correct and I left it as-is.
- **§3.4/§3.5 (Pass B):** the POST scorecard-run path — an existing open finding is `db.bump`ed even when the re-observed `measured_pct` is identical (`domains.py:220-222`), a duplicated `rule_code` in `measurements` is last-wins (`domains.py:168`), and `measurements` is required even on a `CERTIFIED` basis (`domains.py:157-160`). Also `plan-remediation` calls `recompute_domain` without an unconditional touch, so it does **not** advance `Domain.version` (`quality_findings.py:90`) unlike resolve/waive.
- **§3.7 (Pass C):** `select_survivor`'s score-priority tie-break has a fourth fallback on insertion sequence after `created_at` (`services.py:302-307`); `REJECT`/`REWORK` return before any recompute or version bump (`merge_proposals.py:139-149`); `override_justification` is schema-validated with min length 0 and only enforced at >=20 in the `MEDIUM` branch.
- **§3.8 (Pass C):** `clear_notifications`' `include_revision` flag — apply clears `acknowledged_at` but leaves `acknowledged_revision` intact, while withdraw clears both (`services.py:417-426`, `change_requests.py:340-350`). My §2.1 insert pins the generic error for the submit/review/withdraw identity-equality checks, so Pass C should stay consistent with it rather than restate it.

## Step 9: Complete PRD — 2026-09-03T06:29:00.000Z (pass B of 3)

### Pass B summary (verbatim)

Pass B complete. Summary below.

## Size

| | lines | chars |
|---|---|---|
| PRD_COMPLETED.md before Pass B | 409 | 108,885 |
| PRD_COMPLETED.md after Pass B | 409 | 115,373 |

No new sections, paragraphs, or lines — all 14 edited lines (176, 180, 184, 186, 188, 190, 204, 206, 208, 212, 216, 218, 222, 224) were revised in place. Pass A's 26 edits are intact (`diff PRD.md PRD_COMPLETED.md` still shows all of Pass A's line numbers).

## Counts
- ambiguity-pins: 27
- mismatch-revisions: 4

## Changes

§3.3 — quality rules
- §3.3 — insert — ambiguity — `rule_code` uniqueness scan is an exact-string comparison across **every** rule of the domain regardless of `status`, so retiring a rule does not free its code — `routes/quality_rules.py:47` (`db.rules_of`, not `active_rules_of`)
- §3.3 — insert — ambiguity — intra-step check order pinned: duplicate `rule_code` → `ERR_OWNER_NOT_PRINCIPAL` → weight budget — `routes/quality_rules.py:47-57`
- §3.3 — insert — ambiguity — PATCH keeps creation bounds (`threshold_pct` 0.00–100.00, `weight_points` 1–100) — `routes/quality_rules.py:106-107`
- §3.3 — insert — ambiguity — budget re-validated on every modification leaving the rule `ACTIVE` (excluding its own stored weight), and not evaluated at all on a retiring modification — `routes/quality_rules.py:21-27,125-130`
- §3.3 — insert — ambiguity — `RETIRED → ACTIVE` is rejected with `ERR_INVALID_STATE_TRANSITION`; re-sending the rule's existing `status` is a no-op that skips both the transition guard and the open-finding check — `routes/quality_rules.py:113-123`
- §3.3 — insert — ambiguity — every accepted PATCH bumps the rule's own `updated_at`/`version` (even an empty body), and no rule write recomputes anything on the domain, so `Domain.version` is untouched — `routes/quality_rules.py:138` (no `touch_domain`)

§3.4 — scorecard runs
- §3.4 — insert — ambiguity — `measured_pct` is 0.00–100.00 — `routes/domains.py:167`
- §3.4 — insert — ambiguity — `measurements` is mandatory **even on a `CERTIFIED` basis** (empty array acceptable on either basis) — `routes/domains.py:157-160` (hand-off 2c)
- §3.4 — insert — ambiguity — duplicated `rule_code` in `measurements` is last-wins, discarded silently rather than rejected — `routes/domains.py:161-168` (hand-off 2b)
- §3.4 — **revise** — **mismatch** — the "`CERTIFIED` <= `PROVISIONAL`" claim was a false universal: a rule with `threshold_pct` 0.00 passes on an imputed 0.00 and earns full weight, so it can lift the `CERTIFIED` score above the `PROVISIONAL` one — `services.py:236-237`
- §3.4 — insert — ambiguity — a rule whose `threshold_pct` is 0.00 can never fail/breach — `services.py:236`
- §3.4 — insert — ambiguity — a deduped finding keeps its original `scorecard_run_id`, `opened_at`, `status` (a planned finding stays planned), `assigned_steward_id`, `due_at`, `plan_note`, and its assignee's load is unaffected — `routes/domains.py:219-223`
- §3.4 — insert — ambiguity — the refresh is an unconditional mutation: `updated_at`/`version` move even when the re-observed `measured_pct` is identical — `routes/domains.py:222` (hand-off 2a)
- §3.4 — insert — ambiguity — a new finding's full initial field shape (current run's id as `scorecard_run_id`, `opened_at` from the clock, eight named fields null) — `routes/domains.py:224-240`

§3.5 — findings
- §3.5 — insert — ambiguity — re-planning an already-`REMEDIATION_PLANNED` finding yields the generic `ERR_INVALID_STATE_TRANSITION`, not `ERR_FINDING_ALREADY_CLOSED`; a plan cannot be re-assigned or re-dated — `routes/quality_findings.py:69-73`
- §3.5 — insert — ambiguity — `plan-remediation` does **not** advance `Domain.version` (no unconditional touch; the recompute finds nothing moved), unlike resolve/waive; the assignee's own row is bumped by the load recount — `routes/quality_findings.py:89-90` vs `:124-125`, `services.py:104-106` (hand-off 3)
- §3.5 — insert — ambiguity — `verified_measured_pct` is 0.00–100.00 — `routes/quality_findings.py:99`
- §3.5 — insert — ambiguity — resolution clears no planning field (`assigned_steward_id`, `planned_by_steward_id`, `due_at`, `plan_note` all persist); `Domain.version` advances whether or not the posture moved — `routes/quality_findings.py:115-125`
- §3.5 — insert — ambiguity — an `OPEN` finding has a null `planned_by_steward_id`, so no SoD comparison is made and any entitled data owner may waive it — `routes/quality_findings.py:142`
- §3.5 — insert — ambiguity — `waiver_justification` is stored on the row and returned — `routes/quality_findings.py:150`, `serialize.py:105`
- §3.5 — insert — ambiguity — waiver retains the planning fields and advances `Domain.version` by one on either path — `routes/quality_findings.py:148-157`

§3.6 — master records
- §3.6 — insert — ambiguity — `attributes` must be a JSON object but its individual values are not type-checked — `routes/master_records.py:26`, `validation.py:150-156`
- §3.6 — insert — ambiguity — the `natural_key` duplicate scan is exact-string and state-blind: a quarantined or merged-away row still blocks re-ingestion from the same system — `routes/master_records.py:35-39`
- §3.6 — insert — ambiguity — the staleness day count is floored at zero, so a `last_verified_at` at or after the clock earns the full 20 recency points — `services.py:78`, `util.py:72-77`
- §3.6 — insert — ambiguity — on the `CANDIDATE` path a supplied `last_verified_at` carries no ordering constraint against the stored instant — `routes/master_records.py:110-119`
- §3.6 — insert — ambiguity — rehabilitation errors named: omitting `last_verified_at` → `ERR_INVALID_REQUEST`; not strictly later → `ERR_INVALID_STATE_TRANSITION` — `routes/master_records.py:112-116`
- §3.6 — insert — ambiguity — curation accepts only `CANDIDATE`/`QUARANTINED`; `CURATED` or `MERGED_AWAY` → `ERR_INVALID_STATE_TRANSITION`, and that state check precedes the `ERR_SOURCE_NOT_CERTIFIED` check — `routes/master_records.py:101-108`
- §3.6 — insert — ambiguity — curation recomputes `completeness_pct` as well, bumps the record, and leaves `Domain.version` untouched — `routes/master_records.py:123-125`, `services.py:86-89`
- §3.6 — **revise** — **mismatch** — `PUBLISHED → RETRACTED` was scoped to "a decertification cascade"; it fires on **any** recompute that drives the posture into `FROZEN` (incl. quality debt reaching 40.00), and `published_master_record_count` is re-derived by the whole-table recount rather than "decremented by one" — `services.py:171-183`
- §3.6 — **revise** — **mismatch** — hop 4's input set is selected on the **publication** dimension: only records with `publication_status` `PUBLISHED` are retracted+quarantined; a `CURATED`-but-never-published (or already `RETRACTED`) record keeps its `curation_status` and null `quarantine_reason` — `services.py:128-135` (hand-off 1)
- §3.6 — **revise** — **mismatch** — the two-dimension coupling sentence reworded so the causality matches hop 4 (being `PUBLISHED` is what selects the record, not reaching `QUARANTINED` that forces retraction) — `services.py:130-134`

## Hand-off items — all three resolved
1. **§3.6 hop-4 mismatch — resolved.** Verified `services._freeze_cascade` at `services.py:128-139`: the loop guard is `record["publication_status"] == "PUBLISHED"` only. §3.6 line 222 now pins the publication-dimension selection and explicitly says a `CURATED`-unpublished record is left alone. §3.2's hop-4 wording was already correct and was left untouched.
2. **§3.4 POST run path — resolved (all three sub-items).** Verified `domains.py:219-223` (unconditional `db.bump(existing)`), `domains.py:161-168` (`measurements[code] = measured`, last-wins), `domains.py:157-160` (`measurements` required regardless of `basis`). All three pinned in §3.4 lines 184 and 190.
3. **§3.5 plan-remediation version — resolved.** Verified `quality_findings.py:89-90` calls `recount_steward_load` + `recompute_domain` with **no** `db.touch_domain`, versus `:124-125` and `:156-157` which do. Since planning moves the finding between two open-set statuses, `recompute_domain` returns `changed=False` and no bump occurs. Pinned in §3.5 line 204.

## Deliberately left to Pass C
- **§3.7** (`merge_proposals.py`, `services.match_score` / `match_confidence` / `select_survivor` / `apply_survivorship`). Two things I noticed while cross-checking but did **not** edit: `select_survivor`'s tie-break key is `(-survivorship_score, -last_verified_at, created_at, _seq)` — the final insertion-sequence tie-break is unmentioned in §3.7; and `apply_survivorship` treats a present-but-empty-string survivor value as present (not a gap), which §3.7's "present and non-null" wording happens to already cover.
- **§3.8** (`change_requests.py`, `services.assess_impact` / `freeze_window` / `window_conflicts` / `calendar_capacity_exceeded` / `clear_notifications` — note `clear_notifications`'s `include_revision` flag differs between apply and withdraw).
- **§3.9** (`consumer_subscriptions.py`).

## Cross-cutting note for Pass A's sections (not edited)
- §2.7's enumeration of two-decimal quantities omits `posture_multiplier_applied`, which `routes/domains.py:206` rounds with `round2` and `serialize.py:90` emits as a 2dp number. §3.4 already states the three literal values (1.00 / 1.25 / 1.50), so nothing is under-determined — but §2.7's list is incomplete if you want it exhaustive.

## Step 9: Complete PRD — 2026-09-03T06:46:00.000Z (pass C of 3 — final)

### Pass C summary (verbatim)

Pass C is complete. Final verification run confirms integrity.

## Result

**Size**: PRD_COMPLETED.md was 409 lines / 115,373 chars before my pass → **409 lines / 127,389 chars** after (+12,016 chars). Versus PRD.md (409 lines / 101,125 chars), the finished file is +26,264 chars across all three passes, with **53 of 409 lines changed** (paragraph-level edits only; no lines added or removed, no new sections).

**Counts for Pass C**: 18 paragraphs edited, carrying **43 ambiguity-pins** and **3 mismatch-revisions**.

### Mismatch-revisions (PRD contradicted impl)
- **§3.8 apply — revise — mismatch** — the four preconditions were listed clock-before-posture; impl checks posture first, so a frozen domain whose instant has not arrived returns `ERR_DOMAIN_POSTURE_BLOCKED`. Reordered and declared the order normative — `change_requests.py:280-297`.
- **§3.9 staling — revise — mismatch** — "it happens when … `authoritative_source_code` becomes null" omitted the weight-driven freeze; `_freeze_cascade` stales on *any* recompute into `FROZEN`. Also split the two routes' scopes (apply-route reaches any `status` and keys on `lineage_revision`; freeze-route ignores the revision and only touches `ACTIVE` rows) — `services.py:128-139`, `change_requests.py:337-343`.
- **§3.7 survivorship — revise — mismatch** — "the score … is used only afterwards to fill in the field map" is false; the field map is settled key-by-key on presence — `services.py:310-331`.

### Ambiguity-pins (grouped by paragraph)
- §3.7 creation — insert — entitlement runs against the *survivor's* domain and before both linkage checks; cross-domain precedes self-merge; creation imposes no curation/publication/domain-state precondition and never moves `Domain.version` — `merge_proposals.py:28-45`.
- §3.7 review — insert — non-`PROPOSED` yields generic `ERR_INVALID_STATE_TRANSITION` (not `ERR_PROPOSAL_NOT_UNDER_REVIEW`); SoD is *not* enforced at review; no posture/status consulted, no domain touch — `merge_proposals.py:100-114`.
- §3.7 decide — insert — `REJECT`/`REWORK` return immediately after the status write: none of the four MERGE preconditions apply and neither recomputes the domain; `rework_note` is validated then discarded (no field on the row) — `merge_proposals.py:124-149`.
- §3.7 MERGE gate — insert — order pinned, with the explicit note that this path puts the posture gate *ahead* of the curation check, diverging from §2.9's generic sequence (verified against `master_records.py:134-144`, which does the reverse); domain `status` not examined; `ERR_SOURCE_NOT_CERTIFIED` fires before the confidence bar; `LOW` before `MEDIUM` — `merge_proposals.py:152-175`.
- §3.7 `override_justification` — insert — no schema-level minimum (`opt_str(…, 0)`), so short/empty passes validation everywhere except the `MEDIUM` branch, which returns `ERR_MATCH_CONFIDENCE_TOO_LOW` (422) not `ERR_INVALID_REQUEST`; stored only on `MERGE` and only when supplied — `merge_proposals.py:127,172-184`.
- §3.7 survivorship — insert — literal variant spellings `SOURCE_PRIORITY` / `SCORE_PRIORITY` (previously unspecified anywhere in the PRD) and the final insertion-sequence tie-break — `services.py:287-307`.
- §3.7 hop 2 — insert — gap test is presence+non-nullity, so an empty string on the survivor is *not* a gap (though `completeness_pct` counts it unpopulated), and a null-on-both key is written null with the map still crediting the loser; survivor's `version` moves even when nothing was filled; loser is not re-derived — `services.py:310-331`, `merge_proposals.py:187-188`.
- §3.7 rescore — insert — the candidate-eligibility failure is `ERR_INVALID_STATE_TRANSITION`, checked after the `REWORK` check and before the floor; nothing but the proposal row moves — `merge_proposals.py:215-236`.
- §3.8 creation — insert — the per-type `proposed_values` key checks are schema-level 400s settled *before* `domain_id` resolution (missing/null/empty-string, non-enum `target_classification_level`, non-string node keys); extra keys stored verbatim — `change_requests.py:50-79`.
- §3.8 submit — insert — wrong status is `ERR_INVALID_STATE_TRANSITION`; the three checks run status → domain `ACTIVE` → requester identity — `change_requests.py:145-152`.
- §3.8 decide — insert — non-`UNDER_REVIEW` errors before the reviewer comparison; `review_note` is written on all three branches and nulled when omitted, clearing an earlier cycle's note — `change_requests.py:193-226`.
- §3.8 schedule — insert — `APPROVED`-only error id; lead-time → separation buffer → capacity order; the 30-day neighbour boundary is inclusive and non-structural `SCHEDULED` rows never count; the fan-out set is recomputed at schedule time (not replayed from the assessment); `pending_change_request_id` is a single slot, so a second schedule re-points a consumer and drops it from the older request's ack gate — `change_requests.py:241-266`, `services.py:401-414`.
- §3.8 apply — insert — the ack gate keys on the pending pointer alone; the two non-uplift types alter nothing on the domain but the revision counter; hop 2 clears the pointer unconditionally, whatever request it named; lineage staling reaches subscriptions of any `status`; `acknowledged_revision` survives apply — `change_requests.py:291-351`.
- §3.8 withdraw — insert — terminal state errors before the identity comparison; all four notification fields cleared regardless of subscription status, and the release empties the slot rather than restoring an older notification; only a withdrawal from `SCHEDULED` moves `Domain.version`; `submitted_at`/`earliest_apply_at`/`scheduled_apply_at`/impact figures/`reviewer_steward_id`/`review_note` are all retained — `change_requests.py:369-394`, `services.py:417-426`.
- §3.9 registration — insert — the `consumer_code` scan is system-wide, exact-string and status-blind; the clearance check precedes it — `consumer_subscriptions.py:36-44`.
- §3.9 lineage — insert — already-`DOCUMENTED` is `ERR_INVALID_STATE_TRANSITION`, positioned after array shape validation and ahead of the four content checks; non-string/empty entries are schema violations; `ERR_AUTHORITATIVE_SOURCE_UNDEFINED` precedes the three path comparisons; a `SUSPENDED` subscription may still be documented; `Domain.version` untouched — `consumer_subscriptions.py:107-135`.
- §3.9 acknowledge — insert — a repeat acknowledgement on a still-pending notification is accepted and re-stamps both fields; no domain mutation — `consumer_subscriptions.py:149-156`.
- §2.7 (authorized exception i) — insert — added `posture_multiplier_applied` (rounded at `routes/domains.py:206`, emitted 2dp at `serialize.py:90`) plus `name_similarity_pct` and `key_overlap_pct` (`serialize.py:129-130`) to the two-decimal enumeration.

### Hand-off items
1. OK — insertion-sequence tie-break added (`services.py:302-307` confirmed as `(-score, -last_verified_at, created_at, _seq)`).
2. OK — `REJECT`/`REWORK` early return pinned (`merge_proposals.py:139-149`).
3. OK — `override_justification` min-0 schema vs >=20 only in `MEDIUM` → 422 pinned.
4. OK — empty-string survivor value treated as present, pinned with the contrast against `completeness_pct`.
5. OK — Confirmed with one correction to the hint: **apply never calls `clear_notifications` at all** — it inlines the clearing twice (`change_requests.py:322-324` in hop 2 and `346-348` in the release loop), both leaving `acknowledged_revision`; withdraw calls `services.clear_notifications` with the default `include_revision=True`, clearing all four. The `include_revision=False` branch is therefore dead code, so I pinned the observable apply-vs-withdraw asymmetry rather than the flag.
6. OK — Confirmed: single slot, newer request wins, withdrawal empties the slot rather than restoring the older notification — pinned in both §3.8 scheduling and §3.8 withdrawal, plus the ack-gate consequence in apply.
7. OK — Stayed consistent with Pass A's §2.1 rule — referred to "the entitlement error of the acting role" / cross-referenced §2.1 and did not restate the mapping in §3.7/§3.8.

### Integrity verification (final-pass duty)
- Last line is exactly `| `ERR_RULE_WEIGHT_BUDGET_EXCEEDED` | 422 |` — not truncated; the §5 table is complete (67 rows matching `errors.py`'s catalogue).
- All five sections present (`## 1` L3, `## 2` L11, `## 3` L148, `## 4` L274, `## 5` L338) plus all ten §2.x and nine §3.x subsections; line count unchanged at 409.
- Pass A edits spot-checked and intact: §2.1 identity-equality → role entitlement error, §2.1 whitespace-header-counts-as-absent, §3.1 exact-string email comparison, §5 framework-level 404/405 note.
- Pass B edits spot-checked and intact: §3.6 "The day count is floored at zero too…" (absent from PRD.md, present in PRD_COMPLETED.md), §3.5 "planning is the one finding transition that leaves the concurrency anchor alone".
- Nothing under `implementation/`, `test_suite/` or `test_helpers/` was modified; all eight `results.*.json` sweep files are untouched.

### Step 9 aggregate (all three passes)

- Source: `PRD.md` (Step 8 skipped, so no `PRD_FINALIZED.md`). Output: `workspace/PRD_COMPLETED.md`.
- 409 → 409 lines; 101,125 → 127,389 chars (**+26,264**, +26.0%). Paragraph-level edits only; no new lines, paragraphs or sections.
- **89 ambiguity-pins + 14 mismatch-revisions = 103 changes** over 54 distinct lines (A: 19+7, B: 27+4, C: 43+3).

### Orchestrator independent verification of the final artifact

- `wc -lc`: PRD.md 409/101,125 vs PRD_COMPLETED.md 409/127,389 — matches Pass C's report.
- `cmp -s PRD.md PRD_COMPLETED.md` → **differs** (the byte-identical failure mode, where the scan silently never ran, did not occur here); `diff | grep -c '^[<>]'` = 108, i.e. 54 changed lines.
- `tail -3` ends on the complete final table row `| `ERR_RULE_WEIGHT_BUDGET_EXCEEDED` | 422 |` — not truncated.
- `grep '^## '` shows all five top-level sections at lines 3 / 11 / 148 / 274 / 338; 24 headings total.
- `find implementation test_suite test_helpers -newermt "2026-09-03 05:47"` (excluding `__pycache__`) returns **nothing** — no Step 9 pass touched code or tests after the green sweep, so the 201/201 × 8 result still describes the shipped implementation.
- 8 `results.*.json` sweep-evidence files still present.

## Pipeline complete — 2026-09-03T06:47:00.000Z

All nine steps are done. Final state: scaffold triplet + `worklog.md` + `test_helpers/` (9 modules) + `test_suite/` (conftest + 17 files, 201 collected tests) + `workspace/{INSTRUCTION.md, PRD.md, PRD_COMPLETED.md, sweep.log, implementation/}` with `results.1..8.json`. Step 8 was skipped by rule (Step 7 needed zero fixes); `PRD_FINALIZED.md` is therefore intentionally absent.
