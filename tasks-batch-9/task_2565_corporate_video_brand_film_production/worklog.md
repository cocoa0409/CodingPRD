# Worklog — task_2565_corporate_video_brand_film_production

## Step 1: Create task directory — 2026-09-03T12:05:01.752Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2565_corporate_video_brand_film_production` and `.../workspace` using the pre-assigned path (index fixed by scenario number 2565; no auto-allocation performed, per orchestration instructions — up to 32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T13:39:42.851Z

All three artifacts are complete and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2565_corporate_video_brand_film_production/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2565_corporate_video_brand_film_production/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2565_corporate_video_brand_film_production/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    44
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  699

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2565_corporate_video_brand_film_production/`):
- `SCAFFOLD.yaml` — 2599 lines / 132,361 B (§1.0–§1.7 only; no `scaffold_difficulty_design`, no `scaffold_corner_design`)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1462 lines / 94,912 B (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3509 lines / 223,622 B (single top-level key `scaffold_corner_design`)

SCAFFOLD.yaml inventory: 12 entities, 11 state machines (Project, Deliverable, DeliverableVersion ×2 independent axes, ChangeOrder, TalentEngagement, ShootDay, CrewBooking, EquipmentReservation, ComplianceCert, Location), 1 OCC concurrency rule, 12 calculations (13 named variants), 46 validations (contiguous priorities 1–46), 44 endpoints (17 GET + 27 mutating incl. the clock), 46 errors, 6 roles.

§1.8: 9 rule_ids × 19 instances (combinatorial_formula carries 3; every other rule 2).

§1.9: 84 instances across all nine guide sections — entities 12, state_machines 15, calculations 13, validations 14, endpoints 5, errors 13, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1. 62 carry full `test_recipe`s; 22 are `excluded_because` stubs pointing at the §1.8 instance that already covers the corner.

Design adjudications made this session:
- Interval conventions are deliberately opposite and both asserted: crew bookings use a closed interval (touching at 16:00 is a double-book), location capacity uses half-open `[call, wrap)` (touching days do not aggregate).
- Two independent DeliverableVersion axes (`review_status`, `technical_status`) let QC failures be terminal for a cut without touching the review loop; the caption branches (`CAPTION_REQUIREMENT_UNMET` vs `UNREQUESTED_CAPTION_ASSET`) got their own §1.9 instance because §1.8 only pins the duration tolerance.
- Talent pricing carries two orthogonal splits: buyout-vs-union (covered in §1.8) and PROVISIONAL-vs-FINAL basis (covered in §1.9 as `variant_selection` plus a separate `reconciliation` instance for the 655600 → 330000 ledger delta).
- `commitment_budget_allowance` is evaluated last (priority 46) so state/safety defects always report first; the equality case passes (100000 accepted, +1 cent → 422).
- `raw_footage_retention_window` uses 30-day months, so 12 months from 2026-08-01 expires 2027-07-27T00:00:00Z; `archive_status` flips to RETENTION_EXPIRED only strictly after that instant.
- Two claim types I had drafted outside the guide's vocabulary were corrected: the empty-`X-User-ID` corner moved from `rbac/unauthenticated` into `errors/triggerable`, and the crew-scope read corner became `rbac/peer_roles`.
- Two defects were caught by fact-checking recipes against §1.5 before writing: `review-decision` takes `review_note` (not `decision_note`), and the change-order id must be fetched via `GET /deliverables/{id}/change-orders` because DeliverableVersion declares no `change_order_id` output field.

## Step 3: Copy shared files — 2026-09-03T13:39:59.765Z

Copied `./INSTRUCTION.md` → `tasks/task_2565_corporate_video_brand_film_production/workspace/INSTRUCTION.md` (1424 B).

## Step 4: Generate PRD — 2026-09-03T13:54:28.596Z

PRD generation is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2565_corporate_video_brand_film_production/workspace/PRD.md` — **431 lines**, built with 12 chunked heredoc appends (24 → 73 → 110 → 148 → 192 → 216 → 242 → 274 → 304 → 328 → 379 → 431), so no 64k truncation.

**Section list**
- `# Corporate Video & Brand Film Production API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 12 domain-derived subsections: 2.1 Production Roles, Headers and Segregation of Duties; 2.2 API Response Structure (byte-verbatim, `cat`-ed from `skills/prd-bench-doc-generator/section-2.2-response-structure.md`); 2.3 Pagination and List Ordering; 2.4 Record Identity, Timestamps and Version Counters; 2.5 The Logical Production Clock; 2.6 Cents, Rounding and Pinned Evaluation Order; 2.7 The Twin Cost Ledgers: Provisional and Committed; 2.8 The Not-To-Exceed Allowance Gate; 2.9 Cascades, Bubble-Ups and Derived Column Refresh; 2.10 Stale-Version Protection on Cut Uploads; 2.11 Reverse-Reachability Reads and Identifier Resolution Order; 2.12 Rule Precedence
- `## 3. Business Logic & Workflows` — 10 subsections: 3.1 Scoping the Project; 3.2 Budget Top Sheet and Client Sign-Off; 3.3 Casting Talent (buyout loads, union reuse fees); 3.4 Scheduling the Shoot (locations, stage capacity, shoot days); 3.5 Permits, COIs and Compliance Posture; 3.6 Crewing and Equipping a Shoot Day; 3.7 Running the Day (call sheets, wrap, cancellation); 3.8 Post-Production (cuts, QC, client review loop); 3.9 Change Orders and Extra Rounds; 3.10 Delivery, Archive Handover and Raw-Footage Retention
- `## 4. Endpoint Definitions` — 4-column table (Method, Path, Description, Authorized Role(s)), 44 data rows verified (`awk -F'|'` gives 6 fields on every row → exactly 4 columns)
- `## 5. Error Code Catalogue` — 2-column table, 46 data rows

**Tail is complete.** `tail -40` ends on the final catalogue row `| \`ERR_BUDGET_CEILING_EXCEEDED\` | 422 |` — a whole §5 section, no mid-sentence cut.

**Coverage:** 12/12 entities, 11/11 state machines (including the dual-axis `review_status` × `technical_status` pair on DeliverableVersion), 12/12 calculations, 46/46 validations (all carried in §2.12 with explicit priority labels and restated in the owning §3 narrative), 44/44 endpoints, 46/46 errors, 6/6 roles, plus the single `concurrency_rules` entry (`POST /deliverable-versions` / `expected_deliverable_version` / `ERR_STALE_DELIVERABLE_VERSION` 412).

**Hard Contracts**
1. Field-Name Coverage — **PASS**. Scripted diff (PyYAML over SCAFFOLD.yaml vs backticked tokens in PRD.md): 146 entity fields missing `[]`, 74 request-body identifiers missing `[]`, 16 query params missing `[]`, error IDs missing `[]`, state values missing `[]`, role names missing `[]`.
2. Rule Coverage — **PASS**. Every validation, transition, calculation, side effect, default/initial value and sibling branch pair (approve vs request-changes, QC pass vs fail, approve/reject/void, cancel-from-PLANNED vs from-CONFIRMED, release-from-HELD vs from-CONFIRMED, buyout vs union comp) is stated in prose with no pseudocode and no hedging words.
3. §3 Path Purity — **PASS**. The token matcher flagged only two `` `POST` `` occurrences, both domain enum values, not endpoint identifiers: line 209 BudgetLine `category` (alongside `CREW`, `EQUIPMENT`, `LOCATION`, `TALENT`) and line 259 CrewMember `department` (alongside `CAMERA`, `GRIP_ELECTRIC`, `SOUND`, `ART`, `PRODUCTION`). Both are mandated by Contract 1. No URL paths or HTTP methods in endpoint-identifier position appear anywhere in §3.

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. All worked-example figures in the PRD come solely from `SCAFFOLD.yaml`'s own `variants[].difference` fields (budget line 71,661 vs 71,660; talent 1,441,000 / 1,181,125 / 2,238,188 / 1,329,938; change order 566,400 vs 552,000; allowance 300,000 → 315,000).

One authoring note worth relaying: §2.12's priority list is rendered as bullets with explicit `- Priority N:` labels rather than a markdown ordered list, because one item spans priorities 6–15 (the existence checks) and auto-renumbering would have contradicted the stated priority numbers.

**Orchestrator verification (anti-truncation guard):** independently confirmed 431 lines / 88,665 B; `tail -15` ends on `| \`ERR_BUDGET_CEILING_EXCEEDED\` | 422 |`, a complete final table row of a complete §5 — real section boundary, not a mid-sentence cut. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T15:31:00.000Z

All verification sweeps pass. Final state of the generation for `task_2565_corporate_video_brand_film_production`.

## Files written

**`test_helpers/` (9 files, 3,105 lines)**
| file | lines |
|---|---|
| `__init__.py` | 425 |
| `api_client.py` | 260 |
| `api_errors.py` | 148 |
| `assertions.py` | 522 |
| `constants.py` | 239 |
| `factories.py` | 620 |
| `fixtures.py` | 503 |
| `test_users.py` | 93 |
| `types.py` | 295 |

**`test_suite/` (12 files, 7,434 lines, 100 tests)**
| file | lines | tests |
|---|---|---|
| `conftest.py` | 16 | – |
| `test_difficulty_ledger_variants_and_formulas.py` | 574 | 10 |
| `test_difficulty_state_machines_and_cascades.py` | 607 | 8 |
| `test_difficulty_priority_and_boundaries.py` | 583 | 8 |
| `test_difficulty_dependencies_overlap_invariants.py` | 931 | 12 |
| `test_corner_entities.py` | 605 | 11 |
| `test_corner_state_machines.py` | 920 | 11 |
| `test_corner_calculations.py` | 630 | 7 |
| `test_corner_validations.py` | 813 | 11 |
| `test_corner_endpoints.py` | 367 | 4 |
| `test_corner_errors.py` | 700 | 9 |
| `test_corner_rbac_and_layers.py` | 688 | 9 |

## Tests per queue
- **Queue A (Difficulty, §1.8): 38 tests** — all 19 non-stub instances, 2 tests each (the sanctioned path plus its contrast case).
- **Queue B (Corner, §1.9): 62 tests** — 1:1 with the 62 *live* instances. The other 22 named entries in the corner yaml all carry `excluded_because:` (explicitly reassigned to a queue-A instance), so they are correctly not emitted.
- Total **100 tests**, `pytest --collect-only -q` → "100 tests collected".

## Audits (all clean)
- `Design:` tags: 100/100 tagged, 0 untagged, 0 dual-tagged, 0 pointing at a nonexistent instance, every tag the last line of its docstring; coverage diff empty in both directions for both indices.
- Verbatim-citation audit (AST docstring extraction, whitespace-normalised literal match against `workspace/PRD.md`): **0 mismatches** across suite and helpers.
- `pyflakes` over all 12 suite files and all 8 non-`__init__` helpers: exit 0.
- `grep -rin scaffold` over generated code: clean.

## Instances SKIPPED for PRD silence
**None.** Every live instance in both indices survived the two-condition filter. Nine instances did, however, need their *asserted outcome* corrected because the design yaml contradicted the PRD (the PRD wins; the instance's claim type is preserved):

- `budget_variance_cents == 250000` against a null baseline → **0**, per §2.7 line 121 ("reported as 0 for as long as `approved_budget_cents` is null"); replaced with `assert_variance_is_zero_while_unapproved`.
- OCC instance superseded a **DRAFT** cut, which §3.8 line 287 refuses (`ERR_VERSION_DELIVERABLE_MISMATCH`; only `CHANGES_REQUESTED` may be superseded) → `supersedes_version_id` dropped, the parent-bump/version_count claim kept intact.
- Two instances asserted `PROJECT_DELIVERED` straight out of `IN_PRODUCTION`; §3.8 line 299 bubbles to `DELIVERED` **only from `IN_POST`** → added an `_in_post` builder (schedule then cancel the only shoot day, the §3.7 line 281 route) to `test_corner_errors.py` and `test_corner_rbac_and_layers.py`. Without this both tests would have failed against a correct implementation.
- Enum/field defects normalised to PRD spelling: `POST_PRODUCTION`→`CATEGORY_POST`, `PRODUCTION_CREW`→`CATEGORY_CREW`, `BURNED_IN`→`BURNED_IN_SUBTITLES`, `SRT_SIDECAR`→`CLOSED_SRT`, `SCOUTING_HOLD`→`HOLD`, cert `effective_status ACTIVE`→stored status, and the nonexistent `GET /deliverables/{id}/versions`, `scope_locked_at`, `delivered_at` removed. Exact-string timestamp asserts became `assert_at_default_clock`/`assert_instant_equals`; one unverifiable "no Project row is created" claim was reduced to what the API can observe.

## Step 6: Generate implementation — 2026-09-03T15:31:00.000Z

The implementation for task 2565 is complete.

## Files written (all under `.../workspace/implementation/`)

| File | Lines | Role |
| --- | --- | --- |
| `start.sh` | 10 | guarded-install foreground launcher (`exec python3 app.py`), executable |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 61 | app factory, `ApiError`/HTTPException/catch-all handlers in envelope form, `0.0.0.0:$PORT` (default 10000), per-request touch-ledger reset |
| `errors.py` | 67 | 46-code catalog + `ApiError` |
| `store.py` | 150 | in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), UUIDs, `req_` ids, 3-digit ISO, `new_row`/`touch` |
| `envelope.py` | 40 | `meta`/`response_type`/`data` envelope, list `limit`/`offset`/`total_count`/`has_more` |
| `auth.py` | 46 | `X-User-ID`/`X-User-Role`, 6 roles, priority 1→2 |
| `validation.py` | 223 | priority-4 shape checks, priority-5 pagination (1–100 / ≥0) |
| `calc.py` | 226 | 12 calculation rules, `Decimal` + `ROUND_HALF_UP`, three distinct pinned rounding orders |
| `derive.py` | 523 | twin ledgers, all derived columns, 12 serializers |
| `lookups.py` | 84 | 10 existence resolvers, each with its own 404 code |
| `workflow.py` | 163 | allowance gate, `LedgerWatch`, change-order creation, cascades and bubble-ups |
| `routes/` (8 files) | 1313 | `projects`, `deliverables`, `talent`, `physical`, `compliance`, `crew`, `clock` blueprints |

Total 2896 lines. **44 endpoints registered**, verified by enumerating `app.url_map` — an exact match for the PRD §4 table.

## Boot smoke test (PORT 21447, killed by its own PID 749167 only)

Server booted in under 6s and passed three scenario scripts. Verified live: all five PRD worked numbers (per-line 23887 / roll-up 71661; union provisional 8 cycles → 2238188; change order 480000 → 0.18 → 566400), the 315000 post-approval allowance boundary accepted at exact equality while the pre-approval strict ceiling rejects, crew cost 13h → 100000/30000/20000 = 150000, `day_cost_cents` 750000, retention = handover + 360 days, and 15 distinct error codes fired from their correct precedence slots (`ERR_PERMIT_WINDOW_MISMATCH` ahead of the COI check, `ERR_SEGREGATION_OF_DUTIES` on all three decision calls, `ERR_STALE_DELIVERABLE_VERSION` 412, `ERR_CREW_SCOPE_FORBIDDEN`, `ERR_LOCATION_CAPACITY_EXCEEDED` with back-to-back days correctly *not* overlapping, `ERR_CREW_DOUBLE_BOOKED` on a touching endpoint, `ERR_MIN_CREW_NOT_MET`, `ERR_BUDGET_CEILING_EXCEEDED`, …). Full lifecycle DRAFT→SCOPED→IN_PRODUCTION→IN_POST→DELIVERED→ARCHIVED exercised end to end including the cyclic review loop, supersede chain, and `RETENTION_EXPIRED` after a clock move.

Storage is process-local dicts only — no seeding anywhere (grep-confirmed), so every `start.sh` re-invocation wipes all state. `__pycache__` cleaned up.

Two intentional fidelity notes: a second handover reports `ERR_PROJECT_STATE_INVALID` (priority 17 outranks 27, making `ERR_ARCHIVE_ALREADY_HANDED_OVER` unreachable — a scaffold flaw honored literally), and wrap before `wrap_time` reports `ERR_SHOOT_DAY_STATE_INVALID` since no dedicated code is declared. I read only `INSTRUCTION.md`, `SCAFFOLD.yaml`, `PRD.md` and the skill — never `test_helpers/`, `test_suite/`, or either design YAML.

**Orchestrator note:** Steps 5 and 6 were launched as concurrent background agents. Step 6 finished first (~15:10Z) and Step 5 at ~15:31Z. Step 6's agent was given an explicit hard prohibition on reading `test_helpers/`/`test_suite/`/either design YAML and confirmed it never did, preserving the test-blindness contract even though `test_helpers/` existed on disk partway through its run.

## Step 7: Run tests and iterate — 2026-09-03T16:05:24.504Z

All 8 rounds green. The implementation was never touched — every defect was in the test artifact.

## Summary

**Iterations run: 3** (each a full 8-round parallel `setsid nohup` sweep, per-test-server isolation, no early exit)

| Iteration | Result |
|---|---|
| 1 | 50/100 passed — identical 50 failures in all 8 rounds |
| 2 | 99/100 passed — identical 1 failure in all 8 rounds |
| 3 | **100/100 passed in all 8 rounds** (175s/round, 0 failed, 0 errors, 0 skipped) |

Zero flakiness observed: every round of every iteration produced byte-identical pass/fail sets, so all failures were deterministic defects rather than load artifacts.

### Tests deleted: none
All 100 tests are retained. Two assertions were removed and one relaxed under STEP 1c partial-coverage splitting; no whole test failed PRD coverage.

### Fixes applied to `test_helpers/`
- **`test_helpers/api_errors.py`** — `ApiErrorId` enum members were spelled without the `ERR_` prefix (`BUDGET_CEILING_EXCEEDED`), but all 70 references across `test_suite/` use PRD §5's literal spelling (`ApiErrorId.ERR_BUDGET_CEILING_EXCEEDED`). Renamed all 46 members so name == value == PRD §5 spelling, and rewrote the 57 internal references in `HTTP_STATUS_CODES` / `NOT_FOUND_CODES_IN_PRIORITY_ORDER`. Verified post-fix: 46 members, no name/value drift, 46 status mappings, 10 not-found codes. **This single upstream defect caused 48 of the 50 initial failures** — exactly the triage-hint pattern where one fixture bug masquerades as many independent implementation bugs.

### Fixes applied to `test_suite/` (PRD-silence splits, STEP 1b/1c)
- **`test_corner_endpoints.py::test_a_freshly_registered_venue_reads_back_with_its_scheduling_columns_empty`** and **`test_corner_entities.py::test_a_roster_entry_is_minted_with_stamps_a_counter_and_ten_rest_hours`** — removed 4 `assert_at_default_clock(created_at/updated_at)` assertions (**DEFAULT-VALUE / SOURCE SILENCE**). PRD §2.4 defines `created_at` only as "the instant at which the row was first written" and never names its clock source; §2.5 scopes the logical clock to "every window, expiry, lead-time and rush-tier rule" and enumerates the clock-reading values (`effective_status`, `compliance_posture`, `archive_status`, rush tier, lead-time gate, wrap gate) — `created_at`/`updated_at` are absent. Every stamp PRD *does* want off the logical clock is named explicitly (`decided_at`, `submitted_at`, `handover_at`, `call_sheet_published_at`), so wall-clock record stamps are a faithful reading. Both tests keep all other assertions, including `assert_common_fields` (still validates both stamps are ISO-8601 instants). The 5 `assert_at_default_clock` usages on PRD-explicit domain stamps were deliberately left untouched. Scaffold rule: `Corner/endpoints/location_create_then_read_returns_the_same_row_with_zeroed_scheduling`, `Corner/entities/crew_member_creation_stamps_system_fields`.
- **`test_corner_state_machines.py::test_a_second_handover_cannot_restamp_the_retention_clock`** — relaxed the exact-error assertion to `validate_error_is_one_of([ERR_ARCHIVE_ALREADY_HANDED_OVER, ERR_PROJECT_STATE_INVALID])` (**ERROR PRECEDENCE SILENCE**, the explicitly permitted relaxation). This is a genuine internal PRD contradiction: §3.10 names `ERR_ARCHIVE_ALREADY_HANDED_OVER` for a second handover, but handover advances `DELIVERED → ARCHIVED`, so the second call also violates priority 17 ("handover requires `DELIVERED`"), which §2.12 ranks *ahead* of priority 27 while asserting the winner is "fully determined" — making `ERR_PROJECT_STATE_INVALID` the literal reading of the precedence table and `ERR_ARCHIVE_ALREADY_HANDED_OVER` unreachable. I added an explicit `status_code == 409` assertion since PRD §5 maps both candidates to 409, so no HTTP-status rigor was lost, and all substantive assertions (project stays `ARCHIVED`, `handover_at`/recipient unchanged, `retention_expires_at` = handover + 360 days, deliverable `HANDED_OVER`) still pin the real guarantee that the second call restamps nothing. Scaffold rule: `Corner/state_machines/second_handover_on_an_archived_project_is_rejected`.

### Fixes applied to `implementation/`: none
No implementation file was modified (mtimes all pre-date this session). Notably, the pre-existing worklog "fidelity note" about a second handover reporting `ERR_PROJECT_STATE_INVALID` was correct — that behavior follows PRD §2.12's own conflict-resolution mechanism, so the over-specified test assertion was the defect, not the server. Storage remains in-memory dicts with no seeding or on-disk persistence.

One methodology note worth flagging: `workspace/sweep.log` is unreliable for attributing failures, because 8 concurrent rounds write to it and splice each other's lines mid-record — an early read of it pointed at 4 wrong test names and a nonexistent flakiness pattern. The per-round `results.$i.json` files are the only trustworthy source, and all diagnosis above is based on those.

**Orchestrator verification (Step 7 sweep artifacts):** independently re-read all 8 `workspace/implementation/results.{1..8}.json` (all present, ~30.3 KB each, mtime 15:51Z) — every one reports `passed=100 / total=100, failed=0, errors=0`. The clean sweep is real, not a subagent claim.

**Step 8 skip decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 1 `test_helpers/` fix and 3 `test_suite/` edits, so Step 8 runs with those items as `<step_7_diff>`. Note that all four items are test-side, so several may prove to be pure fixture defects with no PRD patch warranted — Step 8 is instructed to patch only genuine PRD silences/mismatches.

## Step 8: Finalize PRD — 2026-09-03T16:07:30.000Z

`PRD_FINALIZED.md` is written. Two edits, both traceable to `<step_7_diff>` items; the third item (the `api_errors.py` enum rename) was a pure fixture defect and produced no PRD change.

## Size delta
- `PRD.md`: 431 lines / 12,654 words / 88,665 bytes
- `PRD_FINALIZED.md`: 431 lines / 12,769 words / 89,375 bytes
- Line delta: **0 (0.0%)**; word delta **+115 (+0.91%)**, byte delta **+710 (+0.80%)**. Two lines touched, no lines added or removed, no new sections.

## Changes
- **§2.4 (Record Identity, Timestamps and Version Counters)** — *revise* — pinned `created_at` and `updated_at` to real wall-clock UTC rather than the logical production clock of §2.5, and clarified that §2.5's "never falls back to real wall-clock time" rule scopes to the logical clock's own value and the derived rules reading it, not to these two record stamps — `implementation/store.py:110-121` (`new_row` → `real_now()`), `implementation/store.py:146` (`touch` → `real_now()`).
- **§3.10 (Delivery, Archive Handover and Raw-Footage Retention)** — *revise* — kept the `archive_status == NOT_PACKAGED` precondition and its `ERR_ARCHIVE_ALREADY_HANDED_OVER` code, but corrected the second-handover outcome: because handover advances `DELIVERED → ARCHIVED`, the repeat call fails the `DELIVERED` precondition and reports `ERR_PROJECT_STATE_INVALID` (409), per §2.12's priority 17 > priority 27 — `implementation/routes/projects.py:175-181`, `implementation/workflow.py:154-159`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 timestamp clock source**
- (a) Subject: the clock source of every system-managed and domain timestamp column, plus anything that consumes `created_at`.
- (b) Paths enumerated: `store.py:19-29` (`CLOCK_DEFAULT`, `clock_now`, `clock_set`), `store.py:81-82` (`real_now`), `store.py:110-121` (`new_row`), `store.py:146` (`touch`), `store.py:149-150` (`by_seq`); grepped every `*_at` assignment repo-wide — `routes/compliance.py:120` (`decided_at` ← `clock_now`), `routes/deliverables.py:245,275` (`submitted_at`, `decided_at` ← `clock_now`), `routes/physical.py:204` (`call_sheet_published_at` ← `clock_now`), `workflow.py:155-156` (`handover_at` ← `clock_now`), `routes/physical.py:294-295` (`pickup_at`/`return_at`, client-supplied); `envelope.py:11` (`api_request_timestamp` ← `real_now`); `derive.py:302-303` (stamps passed through unchanged on reads); all eight `created_at` list-ordering sites (`routes/projects.py:44,61,78`, `routes/deliverables.py:53,132`, `routes/compliance.py:45`, `routes/physical.py:57,95`, `routes/crew.py:85`).
- (c) Adjustment: scoped the sentence to `created_at`/`updated_at` only — deliberately silent on `api_request_timestamp` (also wall-clock, but off the Step 7 site) so no new universal claim is created; and added the explicit "§2.5's no-wall-clock rule governs the logical clock's own value" clarifier so the new sentence does not read as contradicting §2.5, while leaving the five PRD-explicit logical-clock domain stamps (`decided_at`, `submitted_at`, `handover_at`, `call_sheet_published_at`) untouched. I did **not** add the impl's insertion-order (`_seq`) tie-break for equal `created_at` values — no Step 7 item covers list ordering, so it stays under-determined rather than out of scope.

**Edit 2 — §3.10 second-handover error code**
- (a) Subject: the handover endpoint's precondition ordering, and every producer/consumer of `handover_at`, `archive_status` and `ERR_ARCHIVE_ALREADY_HANDED_OVER`.
- (b) Paths enumerated: `routes/projects.py:169-182` (the `DELIVERED` check ahead of the `archive_status` check), `workflow.py:154-163` (`perform_handover` sets `handover_at`, `handover_recipient`, `status = ARCHIVED`, cascades `APPROVED → HANDED_OVER`), `derive.py:190-205` (`retention_expires_at`, `archive_status` — the only reader of `handover_at`), `routes/projects.py:112` (`handover_at=None` at creation), `workflow.py:82-97` (`bubble_project_into_delivered`, the only writer of `DELIVERED`). Confirmed `perform_handover` is the sole writer of `handover_at` and always sets `ARCHIVED` in the same call, so no reachable state has `status == DELIVERED` with `archive_status != NOT_PACKAGED` — `ERR_ARCHIVE_ALREADY_HANDED_OVER` is present but unreachable via this endpoint.
- (c) Adjustment: I did **not** delete the `archive_status`/`ERR_ARCHIVE_ALREADY_HANDED_OVER` precondition, since the impl still performs that check and §2.12 priority 27 still lists it; instead the sentence keeps the check and explains why the `DELIVERED` guard wins on a repeat call. Left §2.12 priority 27 verbatim (it accurately describes the check) and left "stamped from the logical clock" for `handover_at` verbatim (matches `workflow.py:155`), so the two edits do not collide.

**Orchestrator verification:** `workspace/PRD_FINALIZED.md` exists (89,375 B, 431 lines) and differs from `PRD.md` — confirmed non-identical, so the pass genuinely ran.

## Step 9: Complete PRD — 2026-09-03T16:34:11.955Z

Run as **three sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md`, rather than one monolithic scan. Rationale (orchestrator decision, made autonomously): a single subagent asked to walk a 2,896-line implementation against a 431-line/89 KB PRD reliably under-scans and can emit a `PRD_COMPLETED.md` byte-identical to its source, which is indistinguishable from "nothing needed changing". Partitioning by implementation file guarantees each pass has a bounded, checkable surface, and each pass verifies the previous pass's edits are still present before adding its own.

- Pass A — global/plumbing: `app.py`, `envelope.py`, `auth.py`, `store.py`, `validation.py`, `lookups.py`, `errors.py`
- Pass B — computation/derivation/workflow: `calc.py`, `derive.py`, `workflow.py`
- Pass C — endpoint layer: all 8 files under `routes/`

### Pass A result (9 ambiguity-pins, 2 mismatch-revisions)
89,375 → 92,684 chars, 431 lines, 0 line delta.
- §2.1 — revise — ambiguity — whitespace-only headers count as empty (both `ERR_UNAUTHENTICATED`), role comparison exact/case-sensitive — `auth.py:37-40`
- §2.2 success — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9`, minted per response, never persisted — `store.py:66-68`
- §2.2 success — insert — ambiguity — `api_request_timestamp` reads real wall-clock UTC, never the logical clock — `envelope.py:8-12`, `store.py:81-82`
- §2.2 error — revise — mismatch — PRD scoped the error envelope to 4xx only; impl also emits it on the 5xx unexpected-fault path — `app.py:50-52`
- §2.3 — revise — ambiguity — empty/non-numeric/fractional pagination params also raise `ERR_INVALID_PAGINATION`; omitted params silently default — `validation.py:191-218`
- §2.3 — revise — ambiguity — `created_at` ties (ms resolution) break by ascending server creation sequence; the two `call_time` lists share the same final tie-break — `store.py:55-59,117,149-150`
- §2.3 — insert — ambiguity — `total_count` counts filter matches before the page window; `has_more` is `offset + len(page) < total_count`, so an over-range offset gives empty data with `has_more` false — `envelope.py:24-31`, `validation.py:221-223`
- §2.4 — revise — mismatch — PRD implied +1 per mutation (a transition plus its ledger bubble-up would give +2); impl bumps `version`/`updated_at` at most once per row per request — `app.py:27-31`, `store.py:124-146`
- §2.12 p4 — revise — ambiguity — pinned the full request-shape contract (missing/empty/unparseable/non-object body all `ERR_INVALID_REQUEST`; `Content-Type` never inspected; undeclared fields ignored; explicit `null` == absent; booleans rejected as int; fractional rejected as int; NaN/inf rejected; blank strings rejected; enum arrays non-empty and duplicate-free; dates exactly `YYYY-MM-DD`; instants ISO 8601 with zone-less read as UTC) — `validation.py:13-176`, `store.py:85-100`
- §4 preamble — insert — ambiguity — trailing slash equivalent to its absence (`strict_slashes = False`) — `app.py:20`
- §5 preamble — insert — ambiguity — framework-level codes outside the catalogue: `ERR_NOT_FOUND` 404 (no route), `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500, `ERR_REQUEST_FAILED` — `app.py:37-52`

Verified aligned, no change: the 46-entry error→status map in `errors.py` is byte-identical to §5; the six-role table; UUID ids; logical-clock default `2026-08-01T00:00:00Z`; pagination default 10 / band 1–100 / offset ≥ 0; the ten 404 families in `lookups.py`; all ten list endpoints paginate.

### Pass B result (9 ambiguity-pins, 2 mismatch-revisions)
92,684 → 95,192 chars, 431 lines. Pass A edits confirmed intact before and after.
- §2.7 — revise — mismatch — "committed is strictly smaller whenever any such row exists" overstated; qualified to *non-zero* amount (a `unit_rate_cents` of 0 yields a zero row that moves nothing) — `derive.py:95-134`
- §2.9 — insert — ambiguity — a child write reaches the project row **only via the ledger**: `version`/`updated_at` advance only when `provisional_cost_cents` or `committed_cost_cents` actually move, so a REQUEST_CHANGES that consumes a round without spawning a change order leaves the project row untouched; project-row transitions always bump — `workflow.py:23-34`
- §3.2 — insert — ambiguity — fractional `extended_cents`: raw-plus-rounded-markup sum rounded half up to whole cents once at the last step — `calc.py:61-66`
- §3.6 — revise — ambiguity — `scheduled_hours` rounded half up to two decimals, and *that* figure is the operand for all three cost components (10h20s prices as 10.01h) — `calc.py:170`
- §3.6 — insert — ambiguity — the three overtime/straight-time columns are each independently rounded, so they need not sum to `cost_cents`; `cost_cents` is the single rounding of their exact sum and is what the ledgers and `day_cost_cents` consume — `calc.py:179-185`
- §3.6 — insert — ambiguity — `release_reason` is audit-only, not a published crew-booking column — `derive.py:493-507`
- §3.6 — insert — ambiguity — `rental_days` ceiling not bumped on an exact multiple of 24h: exactly 48h bills two days — `calc.py:197-201`
- §3.8 — insert — ambiguity — `version_count` counts every cut including `SUPERSEDED`; `expected_deliverable_version` is a concurrency control only, never stored nor published — `derive.py:363,367-386`
- §3.9 — revise — mismatch — days-to-air was "discarding any fraction" (truncation); impl floors toward negative infinity — `calc.py:135`
- §3.9 — insert — ambiguity — a change order's `decision_note` is audit-only and unpublished, explicitly unlike a certificate's decision note which *is* published — `workflow.py:60`, `derive.py:389-405`
- §3.10 — revise — ambiguity — `archive_status` boundary is strict: a clock resting exactly on `retention_expires_at` still reads `HANDED_OVER` — `derive.py:198-204`

Audited and already uniquely pinned: both ledger status filters and `budget_variance_cents` null handling; the allowance gate's ceiling-vs-1.05 split and strict `>` refusal; every talent-comp formula and all four worked examples (recomputed exact); buyout multiplier bands and the >4 clamp; the 91-day reuse-cycle ceiling; `effective_status`/`permit_ok`/`coi_ok`/`compliance_posture` inclusive boundaries; `day_cost_cents`; both bubble-up guards and the wrap/cancel cascades; all four QC findings with the 1-second inclusive tolerance and fixed append order; rush tiers and producer-fee bands; `retention_expires_at` 30-day months.

### Pass C result (12 ambiguity-pins, 9 mismatch-revisions)
95,192 → 100,491 chars, 431 lines. Passes A and B edits confirmed intact. **All 44 endpoints walked** (9 projects, 10 deliverables, 2 talent, 11 physical, 4 compliance, 7 crew, 1 clock; `routes/__init__.py` only assembles blueprints); all 44 role sets verified against the §4 table with no edit needed.
- §2.1 — revise — mismatch — CrewMember ownership scoping applies to crew-booking reads *only*; shoot-day and crew-roster reads perform no ownership check — `physical.py:62`, `crew.py:29`
- §2.5 — revise — ambiguity — `to_iso8601` required; response `data` carries `current_utc` alone — `clock.py:17-19`
- §2.10 — revise — ambiguity — `expected_deliverable_version` must be ≥ 0; negative is priority-4 `ERR_INVALID_REQUEST`, not a stale-version failure — `deliverables.py:142`
- §2.12 p3 — insert — mismatch — on the *single* booking read the row resolves first, so a bad id yields `ERR_CREW_BOOKING_NOT_FOUND` not the scope error; on the list the scope test does precede pagination — `crew.py:61-64,72-75`
- §2.12 p4 — insert — mismatch — the scope lock never reads the body, so it accepts malformed/non-object bodies — `projects.py:119-122`
- §2.12 p18 — insert — ambiguity — `ERR_DELIVERABLE_STATE_INVALID` also guards submission (`PENDING`/`CHANGES_REQUESTED`), ahead of the cut's review status — `deliverables.py:226`
- §2.12 p22 — insert — mismatch — booking confirmation's day check runs *after* p23; wrap's clock gate also reports `ERR_SHOOT_DAY_STATE_INVALID` — `crew.py:167`, `physical.py:238`
- §2.12 p26 — insert — mismatch — the engagement-status test is evaluated ahead of the p17 project-status test (the sole precedence inversion) — `talent.py:75-79`
- §2.12 p40 — revise — mismatch — `ERR_SCOPE_INCOMPLETE` is raised on three calls, not just scope lock — `projects.py:151`, `talent.py:84`
- §2.12 p42 — revise — mismatch — usage-rights re-checked on scope lock, behind p40 — `projects.py:132`
- §3.1 — revise — ambiguity — lock-scope's rights re-check names `ERR_USAGE_RIGHTS_EXCEED_TERM` and runs after completeness; the call takes no body — `projects.py:126-134`
- §3.2 — revise — ambiguity — `approved_budget_cents` required integer ≥ 0, validated then discarded; missing-line refusal is `ERR_SCOPE_INCOMPLETE` before the ceiling test — `projects.py:144,151`
- §3.3 — revise — mismatch — DRAFT test first, ahead of project status; no-deliverable case is `ERR_SCOPE_INCOMPLETE` — `talent.py:75-85`
- §3.5 — revise — ambiguity — cert `decision` tokens exactly `ISSUE`/`DENY` → `ISSUED`/`DENIED`; `decision_note` ≤ 2000 chars — `compliance.py:109,200-210`
- §3.6 — revise — ambiguity — `release_reason` non-blank, ≤ 2000 chars — `crew.py:182`
- §3.7 — insert — ambiguity — publication has no project-status precondition and no `call_sheet_status` guard: a still-`CONFIRMED` day may be republished, re-running all gates and re-stamping — `physical.py:186,203-205`
- §3.7 — revise — ambiguity — early wrap refused with `ERR_SHOOT_DAY_STATE_INVALID` — `physical.py:239`
- §3.7 — revise — ambiguity — `cancellation_reason` required non-blank, no max length — `physical.py:213`
- §3.8 — revise — ambiguity — review `decision` tokens exactly `APPROVE`/`REQUEST_CHANGES`; `review_note` ≤ 2000 chars and never published — `deliverables.py:27,257-258,276`
- §3.9 — revise — ambiguity — change-order `decision` tokens exactly `APPROVE`/`REJECT`/`VOID`; `decision_note` ≤ 2000 chars — `deliverables.py:28,317`
- §3.10 — revise — ambiguity — `handover_recipient` bounds 1–200; full filter semantics (exact case-sensitive equality; unknown/empty values yield an empty page with `total_count` 0, never an error or 404; undeclared params ignored) — `projects.py:38-43,55-60,73-77`, `deliverables.py:47-52,120-131`, `physical.py:72-80,93-94`, `compliance.py:125-136`, `crew.py:77-84`

Notable non-findings: existence→state→safety→money ordering matches §2.12 everywhere except the three inversions above; pagination-before-parent-404 on all five sub-resource lists matches p5 < p6; sort keys match §2.3; shoot-day confirm correctly checks permit/COI rather than posture; QC and review-decision correctly have no deliverable-state precondition.

### Step 9 totals
- Source `PRD_FINALIZED.md` 431 lines / 89,375 chars → `PRD_COMPLETED.md` 431 lines / **100,491 chars** (**+11,116 chars, +12.4%**; 0 line delta — every edit is an in-paragraph insert or revision, no new sections).
- **30 ambiguity-pins, 13 mismatch-revisions** across the three passes.

**Orchestrator verification:** `PRD_COMPLETED.md` is 431 lines / 100,491 chars and `cmp` confirms it is NOT byte-identical to `PRD_FINALIZED.md` (the tell for a scan that silently no-op'd). All five `##` sections present in order; tail ends on the complete final §5 row `| \`ERR_BUDGET_CEILING_EXCEEDED\` | 422 |`. Spot-checks confirm pass A's `req_` prose and pass B's "negative infinity" floor wording survived the later passes. Steps 8 and 9 touched PRD files only — `implementation/` is unmodified since the green sweep, so the 8× 100/100 `results.{1..8}.json` remain valid.

## Pipeline complete — 2026-09-03T16:34:11.955Z

All nine steps done. Final state: 100 tests, 8/8 sweep rounds at 100/100, `PRD.md` → `PRD_FINALIZED.md` → `PRD_COMPLETED.md` chain intact.
