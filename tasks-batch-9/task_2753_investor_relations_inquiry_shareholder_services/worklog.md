# Worklog — task_2753_investor_relations_inquiry_shareholder_services

## Step 1: Create task directory — 2026-09-04T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2753_investor_relations_inquiry_shareholder_services` and `.../workspace` (pre-assigned path; no index auto-allocation performed).

## Step 2: Generate Scaffold — 2026-09-04T18:04:00.000Z

All three scaffold artifacts for task 2753 are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2753_investor_relations_inquiry_shareholder_services/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2486 | 133,809 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1367 | 85,013 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4192 | 241,730 |

**Lint** — `python3 /home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2753_...`:
```
  §1.5 endpoints declared:    45
  §1.1 entities declared:     9
  §1.8 instances scanned:     18
  §1.9 instances scanned:     76
  Calls scanned (§1.8+§1.9):  785

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**SCAFFOLD.yaml (§1.0–§1.7)**: 9 entities (Company, Contact, Disclosure, InquiryTicket, ResponseDraft, EstimateSubmission, RoadshowEvent, MeetingRequest, TransferAgentInstruction), 45 endpoints, 5 roles (IRAdmin, IRAnalyst, DisclosureOfficer, TransferAgentLiaison, Investor = `entity_backed:Contact`), 14 calculations, 3 OCC rules, 54 validations across 17 priorities, 53 errors. Profile: compliance_audit / temporal_windowing, flat topology, cyclic state machines, `role_model: segregation_of_duties`, `consistency_model: immediate`, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation, selector_policy. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in it.

**§1.8 rule ids (18 instances, 2 each)**: dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**§1.9 sections (88 instances, 12 of them `excluded_because` stubs citing §1.8)**: entities 13, state_machines 19, calculations 12, validations 13, endpoints 6, errors 11, rbac 6, cross_cutting_complexity_layers 7, consistency_model 1.

**Cross-checks passed**: all 53 error ids are referenced by at least one design instance (the last gaps, `ERR_DRAFT_INVALID_STATE` and `ERR_NO_PENDING_REQUESTS`, got two new errors-section instances); no duplicate instance names across the union of both design files; every stub's `difficulty_instance` resolves to a real §1.8 instance name; no forbidden concurrency vocabulary and no difficulty-directive leak in any file. One name had to change to satisfy lint check (b): the priority-ordering validation instance is now `role_check_outranks_path_existence_returns_403`, since the lint only exempts wrong-role probes when the instance name carries a negative token.

No sibling task directory was read at any point; everything was derived from the scenario text plus the skill spec, `references/claim-extraction-guide.md`, and `scaffold_lint.py`.

**Orchestrator verification**: grep for "harder than expert"/"expert level" across all three files — NO LEAK.

## Step 3: Copy Shared Files — 2026-09-04T18:05:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T18:17:00.000Z

PRD generated at `workspace/PRD.md`, written incrementally (1 Write + 5 heredoc appends + 2 small edits).

### Section list
- **§1. Introduction** (3 paragraphs — market-pressure / compliance framing)
- **§2. Global Specifications & System-Wide Principles**: 2.1 RBAC · 2.2 API Response Structure (verbatim from `section-2.2-response-structure.md`, byte-checked) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties and Version Semantics · 2.6 Optimistic Concurrency Control · 2.7 The Disclosure Posture Gate · 2.8 Segregation of Duties and Authorship · 2.9 Numeric Precision, Rounding and Money · 2.10 Rejection Precedence · 2.11 Stored Aggregates, Cascade Depth and Nested Path Resolution
- **§3. Business Logic & Workflows** (9 subsections): 3.1 Registering the Issuer · 3.2 The Shareholder Register, Ownership Analysis and Activist Escalation · 3.3 Shareholder Servicing: Model Access and Threat Assessment · 3.4 The Disclosure Record: Drafting, Publication, Supersession and Withdrawal · 3.5 Inquiry Intake, Sensitivity Scoring and Queue Routing · 3.6 Authoring, Reviewing and Dispatching the Answer · 3.7 Consensus Estimates and the Guidance Framework · 3.8 Conferences, Roadshows and the Allocation Waterfall · 3.9 Transfer Agent Coordination: Record Dates, Dividends and Reversal
- **§4. Endpoint Definitions** — 45 rows, 4 columns
- **§5. Error Code Catalogue** — 53 rows, 2 columns

### Counts
`437` lines / `88,630` chars / `12,706` words.

### Tail
Clean section boundary: last line is the final `| ERR_DIVIDEND_RESERVE_INSUFFICIENT | 422 |` row of the §5 table. No audit footer, nothing mid-sentence.

### Hard Contract Reports
```
Field coverage check:
- entities[].fields: 88 required, 88 present, 0 missing
- endpoints[].request_body: 57 required, 57 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
- endpoints[].output keys: 20 required, 20 present, 0 missing
Status: PASS
```
Two passes run: pass 1 matched identifiers inside any backtick span; pass 2 required each name to appear as a *standalone* backticked token — both diffs empty.

```
Rule coverage check:
- validations[] with priority: 54 checked (17 levels), 54 expressed in prose (§2.10 ordered list + per-workflow sites), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_contact_version / expected_company_version / expected_inquiry_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 34 checked across 7 machines (incl. Contact's two parallel dimensions), 34 fully expressed, 0 missing
- calculations[]: 14 checked (3 dual-variant), 14 fully expressed in operator-free prose, 0 missing
- validations[] conditions: 53 error IDs checked, 53 matchable to a trigger condition in §1–§4 prose, 0 missing
- endpoints[].side_effects / applies_to: 45 endpoints checked, all multi-endpoint applies_to sets enumerated exhaustively, 0 missing
- entities[].fields[] structured content: 88 checked (types, defaults, initial values, constraints), 88 reconstructible from prose, 0 missing
- sibling-branch symmetry: 10 groups checked (DRAFT/PUBLISHED withdraw, ROUTED/ESCALATED fork, APPROVE/REQUEST_CHANGES, ALLOCATED/WAITLISTED, ACKNOWLEDGE/REJECT, DECLARED_RATE/RESERVE_CAPPED, SIMPLE/ANCHORED, CHANGES_REQUESTED/BLOCKED revise, IN_REVIEW/APPROVED block, GRANT/REVOKE), 10 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 936
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- unbacktricked raw path mentions: 0
Status: PASS
```

Also verified mechanically: zero pseudocode operators (`>=`, `==`, `+=`, `&&`, …); zero fuzzy/approximating words; zero OCC race-framing words (`simultaneously`, `first-writer`, `concurrently`); all 53 error IDs, all state values, and all enum values present verbatim.

**One scaffold inconsistency flagged by the doc generator:** `ResponseDraft.revision_round` is `default: 1` / "starts at 1" in `entities[]`, but `POST /response-drafts` side-effects say `revision_round = 0`. The generator followed the entity table (starts at 1, revise rejected once it reaches 3), since the entity definition states it twice and the state-machine precondition is written against it.

**Orchestrator adjudication of that inconsistency:** PRD.md is the contract (Key Principle 1 — "if you must proceed, favor PRD"). Downstream steps were told explicitly that where SCAFFOLD.yaml and PRD.md disagree, PRD.md wins; so `revision_round` starts at 1 for both tests and implementation.

**Orchestrator verification**: `tail -18` confirms the file ends on the last §5 table row; `grep '^## '` confirms all five top-level sections present at lines 3/11/175/329/381. Not truncated — no regeneration needed.

## Step 6: Generate Implementation — 2026-09-04T18:44:00.000Z

(Steps 5 and 6 were launched concurrently; Step 6 returned first, so it is recorded first. Step 5's entry follows below.)

The implementation is complete, boots cleanly, and passes a broad smoke test.

### Modules (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | guarded `pip install`, `export PORT="${PORT:-10000}"`, `exec python3 app.py` (foreground) |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 60 | app factory, 8 blueprints, `ApiError`/`HTTPException`/`Exception` handlers, `app.run(host="0.0.0.0", ..., use_reloader=False)` |
| `store.py` | 217 | in-memory dicts, logical clock (epoch `2026-08-01T00:00:00Z`), `iso`/`rhu`/`floor4`/`new_row`/`touch`/`sorted_rows`, all enums + constants |
| `errors.py` | 76 | all 54 error ids → HTTP status (verified byte-for-byte against PRD §5), `ApiError` |
| `envelope.py` | 62 | success/list/error envelopes (§2.2), pagination (§2.3) |
| `validation.py` | 256 | auth (§2.1), request-shape extractors, query parsing, existence resolvers, Investor ownership |
| `serializers.py` | 186 | 9 entity projections |
| `calc.py` | 218 | 14 calculations + the cascades |
| `routes/companies.py` | 185 | §2.4 clock, §3.1 issuer, §3.7 consensus read |
| `routes/contacts.py` | 224 | §3.2 register/position, §3.3 servicing, §3.7 estimates |
| `routes/disclosures.py` | 135 | §3.4 draft/publish/supersede/withdraw |
| `routes/inquiries.py` | 128 | §3.5 intake/scoring/routing |
| `routes/drafts.py` | 246 | §3.6 author/submit/review/revise/send |
| `routes/roadshow.py` | 160 | §3.8 events + allocation waterfall |
| `routes/meetings.py` | 137 | §3.8 meeting requests + release cascade |
| `routes/instructions.py` | 251 | §3.9 record dates/dividends/reversal |

**2552 lines total. 45/45 declared endpoints registered** (enumerated from `app.url_map` — exact match with PRD §4).

### Interpretation decisions where the PRD was ambiguous

- **§2.10 precedence beats prose order.** Consequences: OCC (7) before draft-state (8) on review; `ERR_CITATION_REQUIRED` (9, cross-entity) before segregation-of-duties (10) and before blackout/selective-disclosure (11) on APPROVE; blackout before selective disclosure inside priority 11.
- **`revision_round` starts at 1** (PRD), not 0 (one scaffold side-effect list).
- **Conditionally-required reason strings** (`reviewer_note` on REQUEST_CHANGES, `rejection_reason` on REJECT) are checked at priority 3, since their error is `ERR_INVALID_REQUEST`. The publish-time guidance-completeness gate is the one exception — it needs the stored row, so it runs after the DRAFT-state check per §3.4 prose.
- **Body-FK order** `company_id → contact_id → event_id → inquiry_id → cited_disclosure_id → linked_prior_inquiry_id`, so `POST /meeting-requests` resolves `contact_id` before `event_id`.
- **Posture re-derivation restricted to the four §2.7 triggers.** Intake and dispatch recount `open_inquiry_count` via a separate `calc.inquiry_count_write` that does *not* touch posture or `posture_recomputed_at`.
- **Escalation wins over `target_queue`** when a NEW ticket scores >= 80.
- `funding_mode` defaults to `DECLARED_RATE` only for `DIVIDEND_PAYMENT`; null on other types when unsupplied.
- Disclosure creation requires the guidance band for `GUIDANCE_UPDATE`; publication additionally requires `metric != NONE` and non-null `period_label`.
- `GRANT_MODEL_ACCESS` on an already-`GRANTED` analyst is idempotent success; ticker validation is lenient (1–8 chars, uppercase-equal).
- RESERVE_CAPPED guards division by zero (rate 0 when `snapshot_shares_total` is null/0).

### Smoke-test results (random high port; server killed by recorded PID, port confirmed free)

An initial launch accidentally bound the default 10000 because `PORT=` was set but not exported — the agent killed that PID immediately (port verified free) and relaunched with `export PORT`. No other process was touched; no broad pattern kills were used.

Verified green: company create + `ERR_DUPLICATE_TICKER`; 401 no-headers; 403 RBAC; contact create with `ownership_pct 6.0`/`TIER_1`; `ERR_STALE_COMPANY_VERSION` 412 ahead of the collective-shares check; position update; disclosure create/`ERR_DUPLICATE_FACT_KEY`/publish; inquiry intake (sensitivity 65 → `DISCLOSURE_COMMITTEE`, SLA +48h) and routing; `ERR_QUEUE_OVERRIDE_FORBIDDEN`; pagination meta and `limit=500` → 400; model-access grant; estimate filing + `ERR_CONTACT_OWNERSHIP_MISMATCH`; consensus read (band 2.125/2.875) and `ERR_NO_ELIGIBLE_ESTIMATES`; full draft lifecycle incl. `ERR_ACTIVE_DRAFT_EXISTS`, stale-review 412, approve→pin→send→inquiry `ANSWERED` with issuer recount; roadshow allocation (scores 99.6 / 45.0, capacity 1), 29-minute double-booking rejection, slot-duration rejection, release→waitlist promotion (`promoted_from_waitlist true`), complete; the depth-4 withdrawal cascade (draft `BLOCKED`/`CITED_DISCLOSURE_WITHDRAWN` with `pinned_disclosure_version` retained → inquiry rewound to `DRAFTING` with fresh SLA → issuer recount); revise round 1→2; `CRITICAL` activist → `BLACKOUT` blocking only the `MATERIAL_NONPUBLIC` draft; dividend flow with per-holder-first rounding (333 × 10.5 → 3497 each, total 6994 — not the 6993 a sum-first order would give), `ERR_RECORD_DATE_IN_PAST`, `ERR_PAYABLE_DATE_TOO_EARLY`, `ERR_DIVIDEND_CYCLE_OVERLAP`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_PAYABLE_DATE_NOT_REACHED`, `ERR_INSTRUCTION_TYPE_NOT_PAYABLE`, RESERVE_CAPPED rate = floor4(1000/500) = 2.0, reversal restoring reserve/paid/received to exactly the pre-execution figures, and the REJECT branch taking no snapshot.

No test-suite or test-helper file was read, listed, or opened at any point; the implementation was built from `INSTRUCTION.md`, `SCAFFOLD.yaml` and `PRD.md` only. Nothing outside `implementation/` was created (no `worklog.md`, no `results.*.json`); `__pycache__` was removed.

## Step 5: Generate Unit Tests — 2026-09-04T19:04:00.000Z

(Launched concurrently with Step 6; returned second.)

### Stage 1 — `test_helpers/` (task root, 9 files, 2,539 lines)
`__init__.py` (51, barrel re-exporting the framework API + every PRD helper), `api_client.py` (296, one method per documented route, boolean/None query-param hygiene), `api_errors.py` (129, `ApiErrorId` enum + `ERROR_HTTP_STATUS`, registers the map via `set_error_http_status_map` at import), `constants.py` (266), `factories.py` (313, optional inputs omitted so declared defaults stay observable; money/rates as JSON numbers), `fixtures.py` (770, five tiers incl. answer-pipeline, consensus seeding, roadshow allocation and dividend chains), `assertions.py` (423, timestamp canonicalisation + per-entity + invariant assertions), `test_users.py` (104), `types.py` (187).

Verified: error catalogue diffs exactly 53/53 against PRD §5 (no extras, no omissions); package imports cleanly.

### Stage 2 — `test_suite/` (conftest + 21 files, 10,049 lines, **177 tests**)
Files `test_01_entity_intake.py` … `test_21_compensating_invariants.py`, numbered breadth-first (corner queue 01–12) then depth (difficulty queue 13–21). Generated by 8 partitioned sub-generators, each restricted to one design-index slice.

### Coverage audit (machine-checked against both yamls)
- **Queue A (Difficulty)**: 18/18 instances translated, all with >=2 tests (several with 3–4). 0 skipped.
- **Queue B (Corner)**: 76/76 non-stub instances translated with >=1 test. 0 skipped. All **12 `excluded_because:` stubs** emitted no tests and every `difficulty_instance` pointer was confirmed to resolve.
- 0 untagged tests, 0 dual-tagged tests, 0 unknown tags, 0 stub tags, 0 shortfalls (94 required tags, 94 covered).
- 535 PRD quotations checked: **all verbatim** (whitespace-normalised substring of `workspace/PRD.md`); every test carries a PRD citation.
- 0 occurrences of `scaffold`/`SCAFFOLD`, `pytest.mark.skip`, `skipif`, `xfail`, `pytest.skip`; byte-compile clean; all 21 modules import cleanly; static check of every `api.*`/`fixtures.*`/`factories.*`/`assertions.*`/`ApiErrorId.*` reference against Stage 1 found 0 missing attributes; pyflakes reports no undefined names; `pytest --collect-only` collects **177 tests** with no errors.

### Instance-level skips
No whole instance was skipped — every non-stub instance is PRD-grounded. Skips were confined to sub-assertions the PRD does not uniquely derive, notably: `created_at` stamped from the logical clock (PRD scopes the clock to deadlines/windows/staleness only — replaced by the clock-pinned `posture_recomputed_at`); absolute `version` numbers on cascade-touched rows (asserted as PRD-stated deltas instead); `ownership_pct`/`target_tier`/`is_guidance` supplied as inputs (PRD never states the outcome); wire format of `record_date`/`payable_date` echoes; `sla_due_at` values at rewind points; `provisional_priority_score` where the lead-time bonus isn't pinned; and same-precedence-level orderings (§2.10 level 13 slot-window vs slot-length, record-date vs payable-lag, and the two level-11 disclosure gates) which were each tested in isolation rather than as an ordering claim. Where the PRD *does* publish precedence (§2.10 level 2 auth > level 4 path existence; level 8 state > level 17 reserve; level 13 temporal > level 14 overlap) the ordering is asserted directly.

### PRD-over-scaffold adjudications applied everywhere
`revision_round` born at **1** (so exactly two revises are accepted and the **third** is refused with `ERR_REVISION_LIMIT_REACHED` at round 3); `request_ledger_total` instead of the non-existent `RoadshowEvent.requested_count`; `payout_ledger` **null** (not `[]`) before execution; `posture_recomputed_at` clock-stamped at registration rather than null. One additional yaml arithmetic error was caught and corrected to PRD: the retail-holder meeting priority is **12.12** (TIER_3 = 20 points), not the yaml's 3.12, which only follows from `UNTIERED`.

### Stray-directory check
`workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` — **no `test_helpers/` or `test_suite/` under `workspace/`**; both live at the task root. All `__pycache__`/`.pytest_cache` removed. Nothing under `workspace/implementation/` was read or written, and `worklog.md` was not touched by the test generator or any sub-generator.

**Orchestrator note on isolation:** Step 5 and Step 6 were launched back-to-back rather than in one message. Step 6's prompt carried an explicit hard prohibition on reading `test_helpers/` or `test_suite/`, and Step 6 reported at exit that no test file was read, listed, or opened. Logical isolation therefore held even though physical (directory-absence) isolation was weaker than the skill's ideal.

## Step 7: Run Tests and Iterate — 2026-09-04T19:26:00.000Z

All 8 rounds are green at 177/177.

**Iterations run:** 2 (baseline sweep + one verification sweep after the fix).

**Tests deleted:** none. The single failing test passed both STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability), and STEP 2 found its setup, request and assertion faithful to PRD.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/store.py` — added an `iso_date()` helper rendering a calendar date as `YYYY-MM-DD`.
- `workspace/implementation/serializers.py` — `instruction_out()` now serialises `record_date` and `payable_date` with `iso_date()` instead of `iso()`.

**Diagnosis of the one real defect:** `test_payable_date_exactly_ten_days_out_is_accepted_after_both_refusals` failed identically in all 8 baseline rounds with `assert '2026-08-15T00:00:00.000Z' == '2026-08-15'`. The implementation parsed the client-supplied `record_date` / `payable_date` into a `datetime` and echoed them back through the full three-fractional-digit timestamp serialiser. PRD §3.9 calls both fields dates ("`record_date` is the date on which the holder snapshot is taken … it is compared against the logical clock at UTC calendar-date granularity"; "`payable_date` is the date the dividend becomes payable … its calendar date must be at least ten days after the record date's calendar date"), and §2.9's three-fractional-digit rule is scoped to "All timestamps" — a distinct set of fields (`created_at`, `published_at`, `executed_at`, `sla_due_at`, …). No PRD sentence licenses reformatting a supplied calendar date into an instant, so echoing the date as given is the uniquely derivable behaviour. Only the serialisation changed; the internal `datetime` representation and all the calendar-granularity comparison logic (`ERR_RECORD_DATE_IN_PAST`, `ERR_PAYABLE_DATE_TOO_EARLY`, `ERR_PAYABLE_DATE_NOT_REACHED`, `ERR_DIVIDEND_CYCLE_OVERLAP`) are untouched.

No load-induced flakiness appeared in either sweep — the baseline union was a single deterministic failure across all 8 rounds, not a timing artifact.

**Final sweep — 177/177 passed in every round:**
```
workspace/implementation/results.1.json  177/177
workspace/implementation/results.2.json  177/177
workspace/implementation/results.3.json  177/177
workspace/implementation/results.4.json  177/177
workspace/implementation/results.5.json  177/177
workspace/implementation/results.6.json  177/177
workspace/implementation/results.7.json  177/177
workspace/implementation/results.8.json  177/177
```

`worklog.md` was not touched by the fix agent. Storage remains in-memory dicts with no seeded data.

**Orchestrator independent verification** (not taking the subagent's word for it, per known failure mode where a Step 7 agent claims a clean sweep with no artifacts on disk):
- All 8 `results.$i.json` exist on disk, mtime 19:23, each ~57 KB; parsed with `json.load` — every round reports `passed=177`, `total=177`, `failed=0`.
- `grep -rn "pytest.mark.skip|xfail|pytest.skip|skipif" test_suite/ test_helpers/` → NO MATCHES, so the green sweep was not bought with skip markers.
- `grep -rn "seed|preload|sqlite|json.dump|/tmp/"` across the implementation → only `envelope.py:26` (`json.dumps` for the response body) plus two comments in `app.py` / `store.py` asserting no seeding. No on-disk persistence, no seeded entities.

**Step 8 skip condition NOT met** (2 `implementation/` fixes were applied), so Step 8 runs.

## Step 8: Finalize PRD — 2026-09-04T19:31:00.000Z

`PRD_FINALIZED.md` written with two surgical edits, both tracing to the single Step 7 implementation fix (`iso_date()` in `store.py` + `instruction_out()` in `serializers.py`).

**Line counts:** PRD.md 437 lines → PRD_FINALIZED.md 437 lines (0.0% line delta; 2 lines revised in place, no lines added or removed, no new sections).

### Changes
- §2.9 (Numeric Precision, Rounding and Money) — revise — appended a scope carve-out to the "All timestamps are ISO 8601 UTC with exactly three fractional-second digits" bullet, stating that `record_date` and `payable_date` are calendar dates rather than timestamps and are rendered as `YYYY-MM-DD` — `implementation/store.py:58-64`, `implementation/serializers.py:169-170`.
- §3.9 (Transfer Agent Coordination) — revise — after the `ERR_PAYABLE_DATE_TOO_EARLY` sentence, added that both fields are calendar dates rather than instants, carried and compared at UTC calendar-date granularity, and rendered in instruction responses as a plain `YYYY-MM-DD` date whenever they hold a value, never reformatted into the three-fractional-digit timestamp form §2.9 prescribes for the entity's timestamp fields such as `executed_at` — `implementation/serializers.py:169-170`, `implementation/routes/instructions.py:48,52,66-67,160`.

### Per-edit pre-edit search log

**Edit 1 (§2.9 bullet)**
- (a) Subject: the global datetime-serialisation format rule — which output fields get the three-fractional-digit instant form and which do not.
- (b) Enumerated/read: `store.py:47-65` (`iso` vs the new `iso_date`); `store.py:121-126` (`common_out` → `created_at`/`updated_at`); every projection in `serializers.py` (`company_out` `blackout_window_start`/`blackout_window_end`/`posture_recomputed_at`; `disclosure_out` `published_at`; `inquiry_out` `sla_due_at`/`answered_at`; `estimate_out` `submitted_at`; `event_out` `window_start`/`window_end`; `meeting_request_out` `requested_slot_start`/`requested_slot_end`/`allocated_at`; `instruction_out` `executed_at`); `envelope.py:17-21` (`api_request_timestamp`); `grep -rn "iso("` across `routes/*.py`, `app.py`, `calc.py`, which found exactly one further callsite, `routes/companies.py:27` (`current_utc`). Result: `iso_date` has exactly two callsites in the whole codebase; every other datetime output still uses `iso`.
- (c) Adjustment: scoped the carve-out to precisely the two named fields ("The two instruction date fields …") instead of a general "date fields are rendered as dates" claim, so no other field is accidentally moved off the three-digit rule.

**Edit 2 (§3.9 record_date/payable_date paragraph)**
- (a) Subject: the full lifecycle of `record_date` / `payable_date` — parsing, storage, every comparison, and output rendering.
- (b) Enumerated/read: `routes/instructions.py:36-38` (`f_dt` → `validation.parse_iso`, lenient ISO parsing, `None` when absent — so `RECORD_INQUIRY` leaves both null and `record_date` is only required for `RECORD_DATE_SET`/`DIVIDEND_PAYMENT`); `validation.py:131-151` (accepts `Z`, offsets, naive, and bare `YYYY-MM-DD`, normalising to UTC); `routes/instructions.py:48-50` (`ERR_RECORD_DATE_IN_PAST`, `.date()`), `:51-55` (`ERR_PAYABLE_DATE_TOO_EARLY`, `.date()`), `:64-69` (`ERR_DIVIDEND_CYCLE_OVERLAP`, `.date()` on both sides), `:159-162` (`ERR_PAYABLE_DATE_NOT_REACHED`, `.date()`); `serializers.py:169-170` (only output site). Confirmed no path reads the time-of-day component and no acknowledge/execute/reverse path re-writes either field.
- (c) Adjustments: (i) wrote "whenever it holds a value" rather than an unconditional "is rendered as a date", because both fields are legitimately null on a `RECORD_INQUIRY` instruction; (ii) deliberately said nothing about the accepted *input* format — the impl's `parse_iso` also accepts full instants and offsets, so pinning input to `YYYY-MM-DD` would have manufactured a new mismatch on an untested path; (iii) phrased the §2.9 reference as applying to "this entity's timestamp fields such as `executed_at`" so the sentence does not appear to weaken the three-digit rule anywhere else.

**Orchestrator verification**: `diff PRD.md PRD_FINALIZED.md` shows exactly two changed lines (138 and 309), both in-place revisions; line count unchanged at 437; tail still ends on the final §5 error-table row (not truncated).

**Step 9 plan (orchestrator decision, recorded per AUTONOMY directive):** a single Step 9 agent cannot exhaustively walk 2552 lines of implementation across 17 modules without truncating its scan, and a byte-identical `PRD_COMPLETED.md` would be proof the scan never ran. Step 9 is therefore executed as FOUR SEQUENTIAL, module-partitioned passes over one shared `PRD_COMPLETED.md`: pass 1 performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md` and covers the global/infrastructure modules; passes 2–4 must NOT re-copy, and each edits the file already on disk. Partition: (1) `store.py`, `errors.py`, `envelope.py`, `validation.py`, `serializers.py`, `app.py`; (2) `calc.py`, `routes/companies.py`, `routes/contacts.py`; (3) `routes/disclosures.py`, `routes/inquiries.py`, `routes/drafts.py`; (4) `routes/roadshow.py`, `routes/meetings.py`, `routes/instructions.py`.

## Step 9: Complete PRD — 2026-09-04T20:07:00.000Z

Executed as FOUR SEQUENTIAL, module-partitioned passes over one shared `PRD_COMPLETED.md`, per the Step 8 plan above. Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2–4 edited the file already on disk and each verified earlier passes' edits had survived before exiting. Total: **73 pins / revisions across 56 changed lines**, 0 sections added or removed.

Cumulative size: `PRD_FINALIZED.md` 437 lines / 89,150 bytes → `PRD_COMPLETED.md` 438 lines / 115,796 bytes (+1 line, +26,646 bytes, +29.9% chars).

---

### Pass 1 — `app.py`, `store.py`, `errors.py`, `envelope.py`, `validation.py`, `serializers.py` (global/infrastructure layer)

Copy confirmed. 438 lines / 92,897 bytes after edits. **11 ambiguity-pins, 2 mismatch-revisions.**

- §2 preamble (line 13) — insert — ambiguity — trailing slash is insignificant; unmatched path → `ERR_INVALID_REQUEST` @404 and unsupported method → `ERR_INVALID_REQUEST` @405, with §2.1 role checks never running for such requests — `app.py:30,41-45`
- §2.1 — revise — ambiguity — a *present but empty* `X-User-ID`/`X-User-Role` also yields `ERR_UNAUTHENTICATED` — `validation.py:28`
- §2.2 — insert — ambiguity — `api_request_id` = `req_` + exactly 20 chars from uppercase letters and digits — `envelope.py:10,14`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the **logical clock**, not wall time; constant across responses until moved, and `2026-08-01T00:00:00.000Z` before any move — `envelope.py:20`
- §2.2 — revise — mismatch — error envelope covers 4xx *and* the 5xx unhandled-fault case (PRD said "4xx status codes" only) — `app.py:47-50`
- §2.3 — insert — ambiguity — `limit`/`offset` are integer literals; unparseable value, `limit`<1 or >100, negative `offset` are **refused** with `ERR_INVALID_REQUEST` rather than clamped; `offset` >= `total_count` legal → empty array — `validation.py:155-175`, `envelope.py:60-62`
- §2.3 — insert — ambiguity — creation-timestamp ties (ubiquitous under a frozen logical clock) break by **insertion order**, never by identifier — `store.py:113-118`
- §2.5 — insert — ambiguity — `id` is a v4 UUID in canonical 36-char lower-case hyphenated form — `store.py:43-44`
- §2.5 — insert — ambiguity — `created_at` records the logical clock's position; `updated_at` is written **equal to** `created_at` at creation — `store.py:91-103`
- §2.9 — insert — ambiguity — output fractional width is exactly 3 digits regardless of input width; input accepts `Z`/`z` or explicit numeric offset (normalised to UTC) and treats zone-less values as UTC; non-string/unparseable → `ERR_INVALID_REQUEST` — `store.py:47-55`, `validation.py:131-143`
- §2.9 — insert — ambiguity — fractional quantities emit as bare JSON numbers, never strings, never zero-padded to nominal scale (`5.0000`→`5.0`, `42.00`→`42.0`); absent values emit `null` — `store.py:82-88`, `serializers.py:31,52,143`
- §2.10 step 3 — insert — ambiguity — strict typing, no coercion: number-typed rejects numeric strings, integer-typed rejects `5.0`, boolean-typed rejects `"true"`/`1`, string-typed rejects empty/whitespace-only — `validation.py:60-128`
- §2.10 step 3 — insert — ambiguity — JSON `null` == omitted (unless an operation says otherwise); absent/zero-length body reads as `{}` and no `Content-Type` is required; unparseable or non-object body fails here; empty-valued query filter == omitted; boolean filters accept only `true`/`false`/`1`/`0` in any case — `validation.py:36-48,55-56,178-209`

Verified-consistent, no change needed: §5 error catalogue is byte-identical in set and status to `errors.py` (53 ids each, `diff` clean); all nine `serializers.py` projections carry exactly the field names §3.1–§3.9 enumerate plus the four universal §2.5 properties, `_seq` never leaked, `payout_ledger` rows exactly `{contact_id, shares_held, amount_cents}`; `has_more = (offset + len(page)) < total_count` equivalent to §2.3 prose; `floor4` already pinned by §3.9's `RESERVE_CAPPED` paragraph; logical-clock epoch, `PAGINATION_*` bounds, `SLA_HOURS`, sensitivity/priority/tier constants all match §2.4/§2.3/§3.5/§3.8/§3.2 exactly.

---

### Pass 2 — `calc.py`, `routes/companies.py`, `routes/contacts.py`

438 lines / 92,897 → 98,038 bytes. Pass 1's edits confirmed intact (§2.2 `req_`+20 spot-check ✓, §2.3 refusal-not-clamping spot-check ✓; `diff` showed pass 1's 13 edits at lines 13, 17, 48–49, 56, 78, 80, 94–96, 138, 140, 148). **15 ambiguity-pins, 4 mismatch-revisions.**

- §2.4 — insert — ambiguity — clock move is unconditional and may run **backwards**; response `data` carries only `current_utc`; the response's own `api_request_timestamp` is read *after* the move — `routes/companies.py:19-27`, `envelope.py:17`
- §2.11 — revise — mismatch — the two nested-path endpoints meet §2.10's shape stage in *opposite* order: consensus resolves the issuer before validating `metric`/`period_label`/`variant`; the estimate listing validates pagination/filters before resolving the contact — `routes/companies.py:99-102` vs `routes/contacts.py:166-171`
- §3.1 — revise — mismatch — ticker rule is "equals its own upper-case form" (digits/non-letters admitted), not "uppercase characters"; uniqueness is exact-string — `routes/companies.py:36`
- §3.1 — insert — ambiguity — no ordering constraint between `blackout_window_start`/`_end`; an inverted or equal pair is accepted — `routes/companies.py:41-42`
- §3.1 — insert — ambiguity — `ticker` filter is exact/case-sensitive; bad `disclosure_posture` fails shape stage — `routes/companies.py:69-70`
- §3.2 — insert — ambiguity — `email` has no length cap and no rule beyond containing `@` — `routes/contacts.py:27-29`
- §3.2 — insert — ambiguity — a body carrying a system-seeded field is not refused; the value is ignored, as is any unread field — `routes/contacts.py:37-51`
- §3.2 — insert — ambiguity — adding a contact leaves the issuer row wholly untouched (no re-derivation, no recount, no version bump) — `routes/contacts.py:52-54`
- §3.2 — insert — ambiguity — position update is not restricted by `contact_type`; an analyst's `ownership_pct`/`target_tier` are derived normally, only the collective sum excludes analysts — `routes/contacts.py:103-116`
- §3.2 — insert — ambiguity — the position write does **not** recount `open_inquiry_count` — `routes/contacts.py:123`, `calc.py:101-110`
- §3.2 — insert — ambiguity — `company_id` filter is not existence-checked; unknown id yields an empty page — `routes/contacts.py:67-68`
- §3.3 — insert — ambiguity — `GRANT_MODEL_ACCESS` has no state precondition: `GRANTED`→`GRANTED` is permitted and still bumps `version` — `routes/contacts.py:138-148`
- §3.3 — insert — ambiguity — `threat_level` is enum-validated whenever present, so a bad value alongside a model-access action still 400s though a good one is ignored — `routes/contacts.py:132-133`
- §3.3 — insert — ambiguity — the posture re-derivation link fires unconditionally (same value, non-activist contact) and does not recount `open_inquiry_count` — `routes/contacts.py:158-159`, `calc.py:101-110`
- §3.4 — insert — ambiguity — link 4 visits each issuer exactly once (version +1 total, not per inquiry), and a link-4 `BLACKOUT` does **not** fire §3.1's draft-blocking chain — `calc.py:130-138`
- §3.7 — insert — ambiguity — estimate `value` has no prescribed scale; stored/echoed at the filer's precision — `routes/contacts.py:192`, `validation.py:112-130`
- §3.7 — revise — mismatch — the `ERR_CONTACT_COMPANY_MISMATCH` rule bites on two operations, not three; it is vacuous for estimate filing, which never raises it — `routes/contacts.py:185-206`
- §3.7 — insert — ambiguity — consensus `metric` excludes the `NONE` sentinel; `period_label` exact/case-sensitive; `variant` in {SIMPLE, ANCHORED} — `routes/companies.py:100-102`
- §3.7 — insert — ambiguity — no upper bound on `submitted_at`; a future-stamped submission stays eligible after a backwards clock move — `routes/companies.py:121`
- §3.8 — revise — mismatch — allocation ranking compares `created_at` at full stored precision (not "millisecond precision") and falls back to insertion order — `calc.py:205-209`

Confirmations, no change needed: `rhu` operand order verified everywhere — `ownership_pct` = (shares/outstanding)x100 then rhu(4) (`calc.py:20-21`); `simple_mean`/`anchored_mean` = sum/count then rhu(4); `band_low/high` = bound x 0.85/1.15 then rhu(4); `dispersion_pct` = (spread / consensus_mean) x 100 then rhu(2) (`routes/companies.py:131,145-150,160,169`). §3.8's pinned order is exact in impl: engagement rounded to 2dp *then* capped at 20; all additive terms including the lead bonus summed; multiplier applied; floor-at-zero on the **product**; single final rhu(2) last (`calc.py:171-184`); lead-time days by floor division (`calc.py:193`), matching "rounded down". §3.5 sensitivity constants/cap and both routing thresholds (50 exclusive, 60 inclusive) match exactly. **No operation in these modules distinguishes explicit `null` from omission**, so pass 1's §2.10 blanket rule was safe at this point.

---

### Pass 3 — `routes/disclosures.py`, `routes/inquiries.py`, `routes/drafts.py`

438 lines / 98,038 → 106,914 bytes. All three spot-checks present exactly once (§2.2 `req_`+20 ✓, §2.3 refusal-not-clamping ✓, §2.4 clock-runs-backwards ✓); diff vs `PRD_FINALIZED.md` then showed 43 changed lines. **14 ambiguity-pins, 5 mismatch-revisions (19 changes over 16 lines).**

- §3.4 — insert — ambiguity — a body-supplied `is_guidance` is still type-validated as a JSON boolean (shape failure if not) and only then discarded for the derivation; `metric`/`period_label`/`guidance_low`/`guidance_high` are accepted and stored on non-`GUIDANCE_UPDATE` types too, and the low<=high check bites whenever both bounds are present regardless of type — `routes/disclosures.py:22-29,49`
- §3.4 — insert — ambiguity — `fact_key` uniqueness is exact and case-sensitive, stored untrimmed — `routes/disclosures.py:33-37`
- §3.4 — insert — ambiguity — disclosure list filters are exact-equality and never existence-checked (unknown `company_id` → empty page, not 404); `period_label` case-sensitive; `is_guidance` matches the stored derivation — `routes/disclosures.py:60-78`
- §3.4 — insert — ambiguity — the publication-time guidance-completeness gate is evaluated **after** the `DRAFT` precondition, so an incomplete `SUPERSEDED`/`WITHDRAWN` guidance row yields `ERR_DISCLOSURE_INVALID_STATE`, never `ERR_INVALID_REQUEST` — `routes/disclosures.py:93-99`
- §3.5 — insert — ambiguity — the issuer-consistency rule binds `contact_id` only; `linked_prior_inquiry_id` is existence-checked and may name another issuer's ticket — `routes/inquiries.py:30-35`
- §3.5 — insert — ambiguity — intake's recount runs after the new row is written (so the new `NEW` ticket is counted) and is the *only* issuer write: posture and `posture_recomputed_at` are untouched despite the version bump — `routes/inquiries.py:55-56` / `calc.py:94-98`
- §3.5 — **revise** — **mismatch** — the escalating branch outranks the queue override: a `DisclosureOfficer` supplying `target_queue` on a `NEW` ticket scoring >=80 is not refused, but the value is discarded and the ticket lands `ESCALATED`/`DISCLOSURE_COMMITTEE`/48h. PRD previously implied the override always replaces the queue — `routes/inquiries.py:113-122`
- §3.5 — insert — ambiguity — neither routing branch writes to the issuer row at all (no recount, no version bump) — `routes/inquiries.py:113-127`
- §3.5 — insert — ambiguity — inquiry list filters exact-equality, not existence-checked — `routes/inquiries.py:64-82`
- §3.6 — insert — ambiguity — at authoring, `cited_disclosure_id` is existence-checked only: any of the four statuses is accepted and the cited row need not share the inquiry's issuer; a cross-issuer `PUBLISHED` citation travels to `SENT` — `routes/drafts.py:27-28`
- §3.6 — insert — ambiguity — draft list filters not existence-checked; a `cited_disclosure_id` filter never matches uncited drafts — `routes/drafts.py:63-78`
- §3.6 — insert — ambiguity — submit-review evaluates state → citation → authorship (the paragraph's own naming order is not the evaluation order), so a non-author submitting an uncited `GUIDANCE_REPEAT` draft gets `ERR_CITATION_REQUIRED` — `routes/drafts.py:94-105`
- §3.6 — insert — ambiguity — an `APPROVE` that supplies `reviewer_note` stores it; one that omits it leaves the existing note rather than clearing it — `routes/drafts.py:163-164`
- §3.6 — **revise** — **mismatch** — the APPROVE citation gate applies to every `disclosure_class`, sits at §2.10 level 9 *ahead* of the segregation-of-duties wall, and the two level-11 gates are ordered blackout-before-selective-disclosure (so a `MATERIAL_NONPUBLIC` draft at a `BLACKOUT` issuer → `ERR_DISCLOSURE_BLACKOUT`). PRD had listed all three as post-wall branch preconditions with blackout first — `routes/drafts.py:139-160`
- §3.6 — **revise** — **mismatch** — the `REQUEST_CHANGES` `reviewer_note` requirement is a request-shape check evaluated before the draft is even resolved, so it beats not-found, stale-version and wrong-state — `routes/drafts.py:123-124`
- §3.6 — insert — ambiguity — **the `revise` null rule**: `body_text`/`disclosure_class` treat `null` as omission and cannot be cleared, while `cited_disclosure_id` is judged on key presence — explicit `null` clears the citation, the only detach mechanism in the system; clearing it does not relax the `GUIDANCE_REPEAT` rule at the next submission — `routes/drafts.py:185,206-211`
- §3.6 — insert — ambiguity — revise recomputes no `sla_due_at` and writes nothing to the issuer — `routes/drafts.py:201-212`
- §3.6 — insert — ambiguity — dispatch's recount is a count only; posture and `posture_recomputed_at` survive unchanged, so an issuer can still read `OPEN` after the clock has entered its blackout window — `routes/drafts.py:244-245` / `calc.py:94-98`
- §2.10 — **revise** — **mismatch** — pass 1's open hatch "Unless a specific operation says otherwise" narrowed to "exactly one exception in the whole system — the `cited_disclosure_id` of a response-draft revision, pinned in §3.6". Hatch closed.
- §2.10 — **revise** — **mismatch** — the claim that same-level checks "are mutually exclusive by construction" was false; it now carries the one enumerated exception (the two level-11 draft-approval gates, blackout winning).

---

### Pass 4 — `routes/roadshow.py`, `routes/meetings.py`, `routes/instructions.py`

438 lines / 106,914 → 115,796 bytes. All four spot-checks survived (§2.2 ✓, §2.3 ✓, §2.4 ✓, §3.6 explicit-null-clears-citation ✓), plus pass 3's §2.10 null tightening confirmed not re-broadened. **19 ambiguity-pins, 3 mismatch-revisions (22 pins across 16 Edit calls).**

- §2.10 — revise — mismatch — the same-level "mutually exclusive by construction ... with one enumerated exception" claim was false for three further pairs; extended (never broadened) to a closed four-item enumeration naming the winners: level-9 event-openness vs contact/issuer match → `ERR_EVENT_NOT_OPEN_FOR_REQUESTS`; level-13 window vs duration → `ERR_SLOT_OUT_OF_WINDOW`; level-13 record-date-past vs payable-lag → `ERR_RECORD_DATE_IN_PAST` — `meetings.py:34-56`, `instructions.py:48-55`
- §3.8 — insert — ambiguity — an inadmissible `slot_minutes` on event creation is `ERR_INVALID_REQUEST` at level 3, decided before `company_id` existence, never `ERR_SLOT_DURATION_INVALID` — `roadshow.py:28-31`
- §3.8 — insert — ambiguity — event list filters are exact-equality and never existence-checked; unknown `company_id` → empty page, `total_count` 0 — `roadshow.py:56-67`
- §3.8 — insert — ambiguity — open-requests takes no body and returns the full updated event row — `roadshow.py:76-84`
- §3.8 — revise — mismatch — "Four rules police the bid" undercounted the five listed rules; corrected and pinned that they apply in the stated (= §2.10) order — `meetings.py:34-56`
- §3.8 — revise — mismatch — "The fourth rule" → "The fifth rule" (renumbering follow-on) — `meetings.py:50`
- §3.8 — insert — ambiguity — the double-booking scan is unbounded by event/issuer (system-wide for that contact); `RELEASED`/`DECLINED` never collide — `meetings.py:50-56`
- §3.8 — insert — ambiguity — meeting-request list filters are exact-equality, not existence-checked; neither the listing nor the single read is scoped by acting identity (an `Investor` sees others' requests) — `meetings.py:80-97`
- §3.8 — insert — ambiguity — a released row retains its `allocated_at` and `promoted_from_waitlist`; nothing is cleared — `meetings.py:115-117`
- §3.8 — insert — ambiguity — promotion reads stored `final_priority_score` (never recomputed) but live `shares_held`; insertion order is the last-resort key; exactly one promotion per release; the response body is the released request, not the promoted one — `meetings.py:124-137`, `calc.py:205-210`
- §3.8 — insert — ambiguity — completion moves the event `version` by exactly 1 regardless of how many rows it declines; `ALLOCATED`/`RELEASED` rows untouched; returns the event with recomputed counters — `roadshow.py:146-160`
- §3.8 — insert — ambiguity — all five counters are maintained by a **full recount** over the event's requests at each trigger (the §2.11 pattern), not incrementally; `request_ledger_total` is the live row count, monotonic because rows are never deleted — `calc.py:212-218`
- §3.9 — insert — ambiguity — `notes` has no length ceiling but empty/whitespace-only is still a shape failure — `instructions.py:43`
- §3.9 — insert — ambiguity — instruction list filters exact-equality, not existence-checked — `instructions.py:98-109`
- §3.9 — insert — ambiguity — the type table governs *required*, not *permitted*: both dates are accepted/stored on types that don't require them and their rules still fire; a rule missing an operand is skipped, not failed — `instructions.py:36-55`
- §3.9 — insert — ambiguity — on input each date accepts a bare `YYYY-MM-DD` or a full ISO 8601 timestamp; a supplied time of day is normalised to UTC and then never compared or rendered — `validation.py:131-151`, `store.py:60-64`
- §3.9 — insert — ambiguity — `declared_rate_cents_per_share` is accepted (still strictly positive) on the non-dividend types; **`funding_mode`'s `DECLARED_RATE` default is type-conditional, so it is `null` on `RECORD_DATE_SET`/`RECORD_INQUIRY`**, an explicit value is kept inertly, and the key is always projected — `instructions.py:39-42`
- §3.9 — insert — ambiguity — `decision_reason` stays null on acknowledge; a `rejection_reason` sent with `ACKNOWLEDGE` is neither an error nor stored — `instructions.py:123-143`
- §3.9 — insert — ambiguity — the payable-date precondition is skipped when `payable_date` is null, and level-13 before level-17 is observable: a `RECORD_DATE_SET` carrying a future `payable_date` yields `ERR_PAYABLE_DATE_NOT_REACHED`, not `ERR_INSTRUCTION_TYPE_NOT_PAYABLE` — `instructions.py:159-165`
- §3.9 — insert — ambiguity — zero qualifying payees is a legitimate execution: empty (not null) `payout_ledger`, `total_payout_cents` 0, balances untouched; a row rounding to 0 cents is kept — `instructions.py:179-195`
- §3.9 — insert — ambiguity — under `RESERVE_CAPPED` a `snapshot_shares_total` of zero yields an effective rate of exactly zero; the division is guarded, not attempted — `instructions.py:170-175`
- §3.9 — insert — ambiguity — the 72-hour boundary is exclusive, and **reversal carries no segregation-of-duties wall** (the submitter or executor may reverse), since §2.8 names acknowledge and execute only — `instructions.py:219-230`
- §3.9 — insert — ambiguity — `executed_at` and `executed_by_user_id` are retained too; reversal writes only `status`, `decision_reason`, `updated_at`, `version` (overwriting any prior `decision_reason`); a `REVERSED` row cannot be reversed again and drops out of the cycle-overlap scan — `instructions.py:232-249`

Pass-4 resolution of the outstanding hand-offs: `funding_mode` is indeed `null` on `RECORD_DATE_SET`/`RECORD_INQUIRY` (confirmed and pinned). Event counters — `roadshow.py`/`meetings.py` never hand-increment; every mutation point calls `calc.refresh_event_counters`, so the PRD's per-link delta prose was mechanism-ambiguous rather than wrong, and is now pinned as a full recount. Posture-write discipline — none of the three pass-4 modules calls `inquiry_count_write` or `posture_write`; `roadshow.py:96-98` only *reads* the stored `disclosure_posture`, which §3.8/§2.7 already describe correctly, so no edit was needed. Incidental and deliberately not edited: `validation.py:155-175` imposes no upper bound on `offset`, consistent with §2.3 which refuses only a *negative* offset; `instructions.py:64-65` defensively skips overlap candidates with a null `record_date`/`payable_date`, an unreachable branch since `DIVIDEND_PAYMENT` requires both; `roadshow.py:106-107`'s missing-contact branch is unreachable because the implementation has no DELETE routes, and was left undocumented rather than inventing reachable behavior.

---

### Orchestrator final verification

- `PRD_COMPLETED.md` = 438 lines / 115,796 bytes vs `PRD_FINALIZED.md` 437 lines / 89,150 bytes. **`cmp` → differs at byte 2650** — NOT byte-identical, so the scan demonstrably ran (the known failure mode where a byte-identical output proves the scan never happened does not apply).
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` → 56 changed lines, all in-place revisions/inserts.
- Heading counts identical in both files: 5 `##` and 20 `###` — no sections added or removed, as required.
- `tail -2` ends on the final §5 error-table row (`| ERR_DIVIDEND_RESERVE_INSUFFICIENT | 422 |`) with a trailing newline — not truncated mid-sentence.
- `find test_suite test_helpers workspace/implementation -newermt "2026-09-04 19:24"` → EMPTY: no implementation or test file was modified after the green 19:23 sweep, so the 8/8 × 177/177 result still describes the artifacts on disk. Steps 8 and 9 touched documentation only.
- All 8 `results.$i.json` retained under `workspace/implementation/`.
- `__pycache__` / `.pytest_cache` directories removed from the task tree.

**PIPELINE COMPLETE** — Step 9 has written `workspace/PRD_COMPLETED.md`.
