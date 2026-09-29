# Worklog — task_2381_lead_service_line_inventory_replacement

## Step 1: Create task directory — 2026-09-02T05:20:11.418Z

Created `tasks/task_2381_lead_service_line_inventory_replacement/` and `tasks/task_2381_lead_service_line_inventory_replacement/workspace/` (pre-allocated task name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-02T09:34:00.000Z

All three artifacts are complete and lint-clean. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2381_lead_service_line_inventory_replacement/`:

**SCAFFOLD.yaml** (1513 lines, §1.0–§1.7, contains neither design key)
- `difficulty_level: expert_plus` — 12 entities, 9 state machines, 10 calculations, 47 validations, 63 endpoints, 57 errors, 6 roles, 2 OCC rules
- Entities: WaterSystem, ServiceLine, EvidenceItem, VerificationCrew, VerificationAppointment, SamplingBatch, InventoryPublication, CustomerNotification, ReplacementOrder, StreetProject, FundingSource, ProgressReport
- Complexity layers: cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency; `consistency_model: immediate`; `role_model: segregation_of_duties`; parallel two-axis ServiceLine state (inventory × replacement); logical clock via `POST /lsl/_clock/set_current_utc` defaulting to `2026-08-01T00:00:00Z`
- Above-expert depth comes from the certainty-score dual basis (RECORDS_BASIS vs FIELD_BASIS over a 5-tier evidence ladder), an 11-step replacement-priority formula with cap-before-penalty-then-floor ordering, waterfall vs pro-rata funding apportionment with an equity-share gate, p90 sampling validation with a strict action level and a confidence floor, and a 7-step program-posture derivation

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (2287 lines) — 9 rules / 20 instances: `dual_variant_calc` (2), `combinatorial_formula` (2), `non_linear_state_machine` (2), `transitive_cascade` (2), `priority_pair_validation_conflict` (3), `boundary_precision_check` (2), `cross_entity_state_dependency` (3), `resource_temporal_overlap` (2), `compensating_invariant` (2)

**SCAFFOLD_CORNER_DESIGN.yaml** (5069 lines) — all 9 sections, 91 instances (73 with full `test_recipe`, 18 `excluded_because` stubs): entities 12, state_machines 18, calculations 12, validations 30, endpoints 5, errors 1, rbac 5, cross_cutting_complexity_layers 7, consistency_model 1

Coverage audit (scripted against SCAFFOLD.yaml):
- 57/57 error ids reachable; 63/63 §1.5 endpoints exercised by setup or trigger calls; all 12 entities, 9 state machines, 10 calculations and 47 validation rules cited in `grounds`; all 6 roles driven; both §1.2.1 concurrency rules have dedicated stale-version instances
- 0 duplicate instance names across the union of both design files; all 18 stub citations resolve to an existing `rule_id / instance_name` pair (I repaired 10 stubs whose rule-id prefix was a paraphrase rather than the literal §1.8 `rule_id`)
- Two SCAFFOLD.yaml defects found and fixed while authoring: a stale `difficulty_level` count comment, and an ambiguous side-effect on `POST /lsl/sampling-batches/{id}/validate` that let the corrosion-control flip read as firing on the REJECTED branch (now pinned to the VALIDATED branch only). One of my own §1.9 instances also had a basis error (a utility-only WATER_SAMPLING item cannot govern under RECORDS_BASIS) and was corrected to 76.00 certainty under FIELD_BASIS.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2381_lead_service_line_inventory_replacement/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2381_lead_service_line_inventory_replacement/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2381_lead_service_line_inventory_replacement/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    63
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  1119

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

The hard constraint held throughout: no sibling `task_*/` directory was listed, globbed, grepped or read; everything derives from the scenario text, the scaffold-generator skill spec, the claim-extraction guide, and this task's own SCAFFOLD.yaml.

## Step 3: Copy shared files — 2026-09-02T09:35:02.260Z

Copied `INSTRUCTION.md` → `tasks/task_2381_lead_service_line_inventory_replacement/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T09:50:25.636Z

PRD generated and verified.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_2381_lead_service_line_inventory_replacement/workspace/PRD.md` — 475 lines.

**Sections written**
- §1 Introduction (3 paragraphs, opened on the domain problem rather than "This document outlines…")
- §2 Global Specifications, 11 subsections: 2.1 RBAC (all six roles individually described; `FieldTechnician` identity translated as `X-User-ID` = the acting `VerificationCrew` row's `id`, the other five as opaque operator identifiers), 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`), 2.3 Pagination and Collection Filtering (10/1/100/0, `created_at` ascending, plus every list filter per collection), 2.4 Resource Identity/Timestamps/Revision Counters (incl. the `ProgressReport` `common_fields: false` exception — only `id` + `created_at`, no `updated_at`, no `version` — and the two embedded array shapes), 2.5 The Logical Clock, 2.6 Numeric Precision and Cent Arithmetic, 2.7 Program Posture (all 7 first-match clauses), 2.8 Derived Values and Cascade Ordering, 2.9 Stale-Version Guards (both OCC rules), 2.10 Request Validation Order (24-rung ladder mirroring priorities 10→90), 2.11 Segregation of Duties
- §3 Business Logic, 8 subsections: 3.1 water system + inventory lifecycle, 3.2 service lines/evidence/governing selection/classification/overrides/certainty, 3.3 crews/appointments/barriers, 3.4 sampling strata + statistical validation, 3.5 publication/certification/notification chase, 3.6 prioritization + street projects + funding sources, 3.7 replacement orders (consent, apportionment, excavation, close-out, flushing, cancellation compensation), 3.8 progress reporting
- §4 Endpoint Definitions — 4-column table, all 63 endpoints
- §5 Error Code Catalogue — 2-column table, all 57 error IDs

**Zero-Silence coverage audit (all mechanical, run twice)**

```
Field coverage check:
- entities[].fields: 141 required, 141 present, 0 missing
- endpoints[].request_body + query_params: 88 required, 88 present, 0 missing
- embedded-object keys + clock outputs: 6 required, 6 present, 0 missing
- enum / state-value tokens: 92 checked, 92 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 47 checked, 47 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 46 checked (across 9 machines), 46 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- errors[] reachable from prose (§1–§3, excluding the §5 table): 57 checked, 57 matchable, 0 missing
- endpoints[].side_effects / applies_to: 121 checked, 121 expressed, 0 missing
- sibling-branch symmetry: 12 groups checked (complete vs no-access; NO_ACCESS vs ABANDONED; VALIDATED vs REJECTED; GRANTED/FULL vs DENIED-NO_RESPONSE/PARTIAL; WATERFALL vs PRO_RATA; RECORDS_BASIS vs FIELD_BASIS; REPLACED_FULL vs REPLACED_PARTIAL; acknowledge vs return; 4 cancel origins; 4 equity tiers; 3 deferral bands; 4 coordination tiers), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1038
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- unbacked occurrences of GET/POST/PATCH/PUT/DELETE/"endpoint"/"/lsl" in §3: 0
Status: PASS
```

**Scaffold observations / defects**
1. `POST /lsl/_clock/set_current_utc`'s `description` is a multi-line YAML scalar containing an embedded newline; any tooling that renders descriptions into a single Markdown table cell will break the row. I collapsed it manually.
2. `POST /lsl/inventory-publications/{id}/certify` has no `inventory_status` guard anywhere in `validations[]`, yet `WaterSystem.inventory_status → PUBLISHED` is only declared from `VALIDATION_PENDING` and `AMENDMENT_PENDING`. Certifying a publication while the system is still in `VALIDATION_PENDING`-ineligible states is only indirectly prevented (drafting is blocked while posture is `FROZEN`, and `DRAFT` forces `FROZEN`). I wrote the constraint at publish time, not certify time, to avoid inventing a rule.
3. `POST /lsl/sampling-batches/{id}/reopen` clears `percentile_90_ppb`, `classification_confidence`, `rejection_reason` and `exceedance`, but not `exceedance_count` — a reopened batch retains a stale exceedance tally until the next validate. I followed the scaffold exactly rather than "fixing" it.
4. `disadvantaged_share_pct` is the name of two different computed fields with two different formulas — on `FundingSource` it is committed-plus-drawn-weighted, on `ProgressReport` it is full-replacement-count-weighted. Real collision risk for implementers; I disambiguated explicitly in both places.
5. Adjacent but differently spelled enum vocabularies for the same concept: `InventoryPublication.basis` uses `RECORDS`/`FIELD_VERIFIED` while `ServiceLine.certainty_basis` uses `RECORDS_BASIS`/`FIELD_BASIS`.
6. Under `PRO_RATA`, the remainder is pushed onto `rows[0]` and is explicitly allowed to be negative; for a single-candidate pool this is harmless, but the scaffold does not state a floor, so an allocation row could in principle be reduced below zero. Documented as specified, without clamping.
7. Two `validations[]` entries share priority 50, and pairs share 60, 65, 70 and 78 — all with disjoint `applies_to` sets, so the ladder stays unambiguous.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped or referenced, and no sibling `task_*/` directory was read.

## Step 5+6 (resume detection) — 2026-09-02T11:20:00.000Z

RESUME MODE re-entry. No worklog entries existed for Steps 5 and 6, but the filesystem
satisfies both checks, so per the resume protocol they were NOT re-run:

- `test_helpers/` present with all 9 modules (`__init__.py`, `types.py`, `api_client.py`,
  `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`,
  `test_users.py`).
- `test_suite/` present with `conftest.py` + 12 `test_*.py` files (test_101..test_109
  depth/difficulty, test_201..test_203 corner/breadth).
- `workspace/implementation/` present with `start.sh` (executable, `exec python3 app.py`),
  `requirements.txt`, `app.py`, `core.py`, `logic.py`, `lookup.py`, and 5 route modules.
- `workspace/PRD.md` verified complete — 474 lines, terminating in the full §5 error-code
  table (`ERR_FUNDING_INSUFFICIENT | 402`), i.e. not a mid-section truncation.

The generation subagents' own summaries for Steps 5 and 6 are unrecoverable (their contexts
were discarded when the earlier run ended), so no verbatim summary can be pasted here.
Proceeding directly to Step 7.

## Step 7: Run tests and iterate — 2026-09-02T12:05:00.000Z

All 8 parallel rounds are green: **79/79 passed** in every round.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each).

**Sweep 1** — 78/79 in all 8 rounds, one deterministic failure (identical in every round, so not flakiness):
`test_201_corner_entities.py::test_system_fields_are_minted_by_the_server_from_the_logical_clock` -> `KeyError: 'data'`.

**Diagnosis:** a test-layer bug, not an implementation bug. The test did

```python
body = validate_success(api.create_water_system(...), 201)
system = body["data"]          # KeyError
```

but the shared runner helper `validate_success` (`prd-bench-local-runner/src/prd_bench_local_runner/testing/validators.py:50`) already **returns `body["data"]`**, not the envelope. It was the only `validate_success` call site in the whole suite, so nothing else was affected.

**Tests deleted:** none.

**Assertion removed under STEP 1c (partial coverage):** one line inside the above test —
`assert system["created_at"].startswith("2026-08-04T07:30:00")`.
Category: **PRD silence on the field's provenance.** PRD §2.4 states only that `created_at` is "an ISO 8601 UTC timestamp with three fractional digits, stamped when the row is first persisted"; §2.5 enumerates the logical clock's consumers as "every deadline, overdue determination, paving-coordination tier and completion-window comparison" — row timestamps are not in that closed list. Two divergent PRD-faithful readers exist (stamp from the logical clock vs. from wall time; the implementation takes the latter, `core.py:new_row` -> `wall_now()`), so the assertion is not uniquely derivable. Scaffold rule that drove it: `Corner/entities/system_fields_are_minted_by_the_server_from_the_logical_clock`.

**Fixes applied to `test_suite/`:** `test_suite/test_201_corner_entities.py`, `test_system_fields_are_minted_by_the_server_from_the_logical_clock` — capture the `requests.Response`, take the resource from `validate_success(response, 201)` and the envelope from `response.json()`, so the retained §2.2 `meta`/`response_type` and §2.4 `id`/`created_at`/`version` assertions actually execute; docstring updated to cite §2.2 and to record why no `created_at` provenance assertion is made.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful on every one of the 79 assertions.

**Orchestrator verification**: `results.{1..8}.json` re-read independently — every round reports `passed=79 total=79`.

**Step 8 skip-condition adjudication**: NOT skipped. The skip condition requires zero iterations
beyond the baseline (0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0
`implementation/` fixes). Step 7 ran 2 sweeps and applied 1 `test_suite/` fix plus 1 STEP-1c
assertion removal, and that removal is precisely a located PRD silence (`created_at`
provenance) that Step 8 exists to pin. Step 8 therefore runs.

## Step 8: Finalize PRD — 2026-09-02T12:12:00.000Z

PRD_FINALIZED.md produced. One edit only.

## Counts
- PRD.md: 474 lines / 100,733 bytes
- PRD_FINALIZED.md: 474 lines / 101,040 bytes
- Line delta: 0 (0.0%); byte delta +307 (+0.30%); 2 lines revised in place, no lines added or removed, no new sections.

## Change
- **§2.4 Resource Identity, Timestamps and Revision Counters** — revise — the `created_at` bullet now states that `created_at`/`updated_at` are read from the server's **real wall-clock time** at write time, not from the logical clock of §2.5, and that logical-clock-fed row values are always named business fields or comparisons; the `updated_at` bullet's "in the same format" becomes "in the same format and from the same wall-clock source". Impl: `implementation/core.py:59` (`wall_now`), `core.py:76-83` (`new_row` -> `iso_ms(wall_now())` for both stamps), `core.py:88-91` (`touch` -> `iso_ms(wall_now())`).

## Pre-edit search log (the one edit)
(a) **Subject:** provenance of server-managed row timestamps (`created_at`, `updated_at`) versus the logical clock, on every entity that carries them.

(b) **Impl paths enumerated (grepped/read):**
- `core.py:59-91` — `wall_now`, `iso_ms`, `new_row`, `touch`: the only two writers of `created_at`/`updated_at` anywhere; both use wall time.
- `grep -rn "created_at|updated_at" implementation/*.py` — every other hit is a *read*: serializer `logic.py:660-666` (`_common`), progress-report serializer `logic.py:889-890`, `routes_orders.py:412-416` (progress report mints `id`/`created_at` from `new_row()`, so append-only reports share the same wall-clock source), and the `by_created_at` list-ordering helper (`core.py:94-95`, used by all 12 collection reads and the `logic.py:48-101` scoped finders). No path rewrites `created_at`, so the retained "never changed afterwards" stays true.
- `grep -rn "db.clock" implementation/*.py` — all logical-clock row writes are named business fields: emitted evidence `observed_at` (`routes_field.py:253`, `routes_inventory.py:112`), `published_at`/`notification_due_at` (`routes_publication.py:150-153`); the rest are comparisons (`logic.py:211,235,343`, `routes_publication.py:116`) plus the clock endpoint itself (`routes_water.py:267-283`). This is what the "named business field or comparison" clause is scoped to.
- `routes_water.py:274-283` + `logic.py:817-831`, `logic.py:205,683` — a clock move does **not** `touch()` notifications or water systems; `overdue` and `program_posture` are derived at serialization time. Checked so the new sentence could not be read as making clock moves refresh `updated_at`.

(c) **Wording adjustment:** two. (1) The wall-clock clause was scoped to the two bookkeeping stamps only, rather than a global "timestamps come from wall time" statement, so `observed_at`/`published_at`/`notification_due_at` are not mis-described. (2) The follow-on clause was left deliberately loose ("always a named business field or comparison") instead of enumerating fields, so the many logical-clock comparison sites stay in scope without asserting a closed list.

## Notes / non-edits
- The `validate_success` envelope confusion was confirmed test-layer only: §2.2 already fixes `meta.api_request_id`, `api_request_timestamp`, `response_type` and `data`, and `core.py:180-190` matches it. `api_request_timestamp` is also minted from `wall_now()` (`core.py:184`), but no assertion on its provenance was weakened in Step 7 and §2.2's "server-generated" is not contradicted, so per the scope note I made no §2.2 edit.
- Out-of-scope observations (deliberately **not** edited, no Step 7 item touches them): §2.5's "each successful clock move recomputes `overdue` ... and then recomputes `program_posture`" and §2.8's "each recompute is a mutation of its own row that refreshes `updated_at` and advances `version`" — the impl derives both on read (`logic.py:830`, `logic.py:683`) and never bumps `version`/`updated_at` on a clock move; and §2.3's "ordered by `created_at` ascending" is implemented as insertion-sequence order (`core.py:94-95`), which differs only for same-millisecond ties.

**Orchestrator note**: Step 8's three out-of-scope observations were correctly left unedited under
Step 8's HARD SCOPE rule (no Step 7 item touches them). They are handed to Step 9, whose full
PRD-vs-implementation scan is exactly the mechanism for resolving mismatches that produced no
Step 7 failure signal.

## Step 9: Complete PRD — 2026-09-02T12:28:00.000Z

All 42 edits landed across 39 paragraphs; headings are byte-identical to the source and the line count is unchanged, confirming every change is an in-paragraph insert/revision with no new sections.

## Files
- `workspace/PRD_COMPLETED.md` (deliverable)
- `workspace/PRD_FINALIZED.md` (source)

## Size
| | lines | chars |
|---|---|---|
| PRD_FINALIZED.md | 474 | 101,040 |
| PRD_COMPLETED.md | 474 | 112,813 |

Char-delta: **+11,773**. Changed paragraphs: 39 (headings identical, no sections added).

## Counts
- **ambiguity-pins: 25**
- **mismatch-revisions: 14**

## Changes
- §2.1 — insert — ambiguity — a header present but empty-string counts as absent for `ERR_UNAUTHENTICATED` — `core.py:endpoint()`
- §2.3 — revise — mismatch — list order is the server's monotonic insertion sequence, not a re-sort by `created_at`; same-millisecond rows keep insertion order — `core.py:94-96`
- §2.3 — insert — ambiguity — filters are exact string equality; the three boolean filters read `true`/`1`/`false`/`0` case-insensitively; a non-matching or unparseable value yields zero rows, never a validation error — `core.py:487-503`
- §2.4 — insert — mismatch — "every mutation bumps `version`" scoped to fields actually stored on the row; serialization-time aggregates are not stored, so refreshing one moves neither `updated_at` nor `version` — `core.py:99-104`, `logic.py:153-185`
- §2.5 — revise — mismatch — a clock move re-derives rather than rewrites: it writes to no row at all (no `updated_at`/`version` on notifications or water systems); response `data` is exactly `{current_utc, previous_utc}` at 200 — `routes_water.py:267-284`, `logic.py:205-235`
- §2.8 — revise — mismatch — derived values split into persisted (service-line fields, progress-report body) vs. serialization-time (all named aggregates/ledgers/postures/flags); refreshing the latter mutates nothing — `logic.py:96-235`
- §2.8 — revise — mismatch — the cascade's water-system steps are re-derivations, so the amendment edge is the chain's only observable water-system mutation — `logic.py:401-452`
- §2.10 — insert — ambiguity — explicit `null` on a required field fails rung 3 and on an optional field takes the default; malformed date/instant/`HH:MM` is `ERR_INVALID_REQUEST` at rung 3, never `ERR_INVALID_DATE_RANGE`; per-field value constraints are evaluated *after* the rung-4 enum pass — `core.py:371-441`
- §3.1 — revise — mismatch — `cct_orthophosphate_mg_l` is nullable and only constrained non-negative; it is not coupled to `cct_optimization_status` — `routes_water.py:47-58`
- §3.1 — revise — ambiguity — empty-inventory and still-`UNCLASSIFIED` failures collapse onto `ERR_INVENTORY_STATE_INVALID`; a bad `target_status` is caught at rung 4 — `routes_water.py`
- §3.1 — revise — ambiguity — corrosion-control PATCH writes each optional field only when its key is present (omitted key preserves, explicit `null` clears) and is not gated on posture — `routes_water.py:225-263`
- §3.2 — insert — ambiguity — fresh-line initial values (`UNKNOWN` materials/classification, `RECORDS_BASIS`, scores 0.0, flag false, evaluated `disadvantaged_status`); no recompute at creation, so the replacement axis stays `NOT_REQUIRED` and `version` stays 1 — `routes_inventory.py:40-70`
- §3.2 — revise — ambiguity — governing-evidence final tiebreak is insertion sequence descending — `logic.py:governing_evidence`
- §3.2 — insert — ambiguity — leaving `UNCLASSIFIED` tests only for one non-retracted item of any type/side; a fully retracted line falls back — `logic.py:401-452`
- §3.2 — insert — ambiguity — the recompute advances `version` unconditionally even when nothing changes, and twice when the replacement axis also moves — `logic.py:401-452`
- §3.2 — insert — ambiguity — a write that both lifts the line out of `UNCLASSIFIED` and satisfies the verified condition makes both hops in one pass — `logic.py:401-452`
- §3.2 — insert — ambiguity — retraction answers with the `EvidenceItem`; the re-derived line is not in the response — `routes_inventory.py`
- §3.2 — revise — ambiguity — override stores `justification` verbatim as the item's `notes`, sets `observed_at` to the logical clock, and answers 200 with the recomputed `ServiceLine` — `routes_inventory.py:150-188`
- §3.3 — revise — ambiguity — cascade evidence takes `observed_at` from the logical clock (not the window) with `notes` null; `observed_side`/`observed_material`/`barrier_reason` null until written — `routes_field.py:251-255`
- §3.3 — insert — mismatch — a barrier report never touches `attempt_count` on either branch; only re-booking advances it — `routes_field.py:276-281`
- §3.4 — revise — ambiguity — `lead_ppb` may not be negative; append/void/validate/reopen all answer 200 with the whole batch — `routes_field.py:380,402`
- §3.4 — insert — ambiguity — sample ordering ties break on `collected_at` ascending then `sample_seq` — `logic.py:sampling_statistics`
- §3.4 — revise — ambiguity — `rejection_reason` is cleared to null on `VALIDATED` — `routes_field.py:454-455`
- §3.4 — revise — mismatch — reopen also resets `exceedance_count` to 0; every superseded statistic is discarded — `routes_field.py:481-487`
- §3.5 — revise — mismatch — the stale DRAFT is deleted outright, so its id stops resolving and later reads answer `ERR_PUBLICATION_NOT_FOUND` — `routes_publication.py`
- §3.5 — revise — mismatch — publish writes `PUBLISHED` over any non-`PUBLISHED` status and bumps `version` only on that write; counts/posture re-derive on the next read; an already-`PUBLISHED` system's `version` does not move — `routes_publication.py`
- §3.5 — revise — ambiguity — `overdue` is strict (clock exactly on `due_at` is not overdue); `sent_at`/`acknowledged_at` are stored verbatim as supplied — `logic.py:229-235`
- §3.6 — revise — mismatch — `consent_barrier_flag` skips `CANCELLED` orders outright and takes the newest surviving order — `logic.py:373-379`
- §3.6 — revise — ambiguity — the street-project link pass re-derives and bumps `version` only on a changed score, and is vacuous in practice since a line's `street_project_id` must resolve at creation — `routes_water.py`
- §3.7 — revise — mismatch — the move to `IN_PROGRAM` is unconditional once the eligibility gate passes; neither `classification` nor intended side is consulted — `routes_orders.py:86-89`
- §3.7 — insert — ambiguity — a non-granting outcome missing `barrier_reason` is `ERR_INVALID_REQUEST` at rung 3, ahead of path resolution and the state check — `routes_orders.py:153-155`
- §3.7 — revise — mismatch — the `GRANTED` branch recomputes the priority in place but does not book the line as mutated, so `updated_at`/`version` do not move — `routes_orders.py:174-176`
- §3.7 — revise — ambiguity — a recanvass advances the line's `version` as well as the order's — `routes_orders.py:137-141`
- §3.7 — insert — ambiguity — the two street-project gates are cleared vacuously by an order with no `street_project_id` — `routes_orders.py:256-258`
- §3.7 — insert — ambiguity — `replaced_sides` is checked by set *and* length (so `["UTILITY","UTILITY"]` is refused), with non-emptiness at rung 3 and membership at rung 4 — `routes_orders.py:322-323`
- §3.7 — insert — ambiguity — a freshly opened order's `flushing_duration_minutes`, `completed_at`, `funding_mode_applied`, `scope`, `cancellation_reason` are null and `replaced_sides` empty — `routes_orders.py:74-83`
- §3.7 — revise — mismatch — every cancel including `DRAFT` re-derives the barrier, recomputes the priority and bumps the line's `version`; `RELEASED` rows stay on `funding_allocations` and are excluded from `allocated_total_cents` — `routes_orders.py:371-386`, `logic.py:837-838`
- §3.8 — insert — ambiguity — the report row records and returns its three filed inputs alongside the computed body — `routes_orders.py:413-424`
- §4 — revise — ambiguity — `data` carries the row named by the path's last identifier segment (override -> `ServiceLine`, sample -> `SamplingBatch`, completion -> `VerificationAppointment`, order transitions -> `ReplacementOrder`); those first two are the only 200-instead-of-201 mints; the clock endpoint returns the bare pair — `routes_inventory.py`, `routes_field.py`, `routes_orders.py`, `routes_water.py:267`
- §5 — insert — ambiguity — three transport-level codes outside the ladder: `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405), `ERR_INTERNAL` (500), all in the standard envelope — `app.py:42-61`

Both user-supplied leads were confirmed against the implementation and fixed (§2.5/§2.8 serialization-time derivation with no `version` bump; §2.3 insertion-sequence ordering). Twelve further mismatches the leads did not mention were found and revised — the most consequential being the destructive stale-DRAFT delete, publish not bumping an already-`PUBLISHED` system, `CANCELLED` orders being skipped by the consent barrier, cancel-from-`DRAFT` still mutating the line, and the `GRANTED` branch not advancing the line's `version`.

---

# PIPELINE COMPLETE — 2026-09-02T12:29:00.000Z

Steps 7, 8 and 9 ran in this resume session; Steps 1–6 were satisfied on disk and correctly
not re-run. Final state:

- `SCAFFOLD.yaml` / `SCAFFOLD_DIFFICULTY_DESIGN.yaml` / `SCAFFOLD_CORNER_DESIGN.yaml` — present
- `workspace/INSTRUCTION.md`, `workspace/PRD.md` (474 lines) — present
- `test_helpers/` (9 modules) + `test_suite/` (conftest + 12 test files, 79 tests) — present
- `workspace/implementation/` (9 modules + `start.sh`) — present, unmodified by Step 7
- **Step 7 green sweep**: `results.{1..8}.json`, every round `passed=79 total=79`
- `workspace/PRD_FINALIZED.md` (Step 8) and `workspace/PRD_COMPLETED.md` (Step 9) — present
