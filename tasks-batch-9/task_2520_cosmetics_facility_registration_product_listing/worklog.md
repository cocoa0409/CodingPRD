# Worklog — task_2520_cosmetics_facility_registration_product_listing

## Step 1: Create task directory — 2026-09-03T05:06:05.203Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2520_cosmetics_facility_registration_product_listing` and its `workspace/` subdirectory. Index 2520 was pre-assigned by the orchestrating caller (no `./tasks/` scan performed — up to 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate scaffold artifacts — 2026-09-03T07:00Z

Generated the three scaffold files from the verbatim scenario description plus the
`prd-bench-scaffold-generator` specification only (no sibling task under `tasks/` was read):

- `SCAFFOLD.yaml` — 3404 lines; §1.0–§1.7 plus preamble keys. 14 entities, 53 endpoints,
  56 validations/errors, 5 roles, deterministic clock + ops sweep. Contains neither
  `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1735 lines; single top-level key `scaffold_difficulty_design`,
  18 instances (9 rule_ids x 2).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4749 lines; single top-level key `scaffold_corner_design`,
  95 instances across the guide's nine sections (71 full recipes + 24 `excluded_because` stubs).

`scaffold_lint.py` verdict: `clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have
reverse-reachability in §1.5` (875 calls scanned).

### Step 2 — subagent summary (verbatim, orchestrator record)

All three scaffold artifacts for task_2520 are complete and lint-clean.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2520_cosmetics_facility_registration_product_listing/`)

| File | Lines | Contents |
|---|---|---|
| `SCAFFOLD.yaml` | **3404** | §1.0–§1.7 + preamble. 14 entities, 53 endpoints, 56 prioritized validations/errors, 5 roles (2 entity-backed), 2 segregation rules, 3 concurrency rules, deterministic clock + `_ops/compliance-sweep`. Contains neither forbidden key. |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | **1735** | Single top-level key `scaffold_difficulty_design`; 18 instances (9 rule_ids × 2). |
| `SCAFFOLD_CORNER_DESIGN.yaml` | **4749** | Single top-level key `scaffold_corner_design`; 95 instances = 71 full `test_recipe`s + 24 `excluded_because` stubs, across entities 15 / state_machines 20 / calculations 15 / validations 21 / endpoints 7 / rbac 6 / complexity_layers 7 / errors 3 / consistency_model 1. |

## Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     71
  Calls scanned (§1.8+§1.9):  875

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notes

- Structural checks pass independently: no duplicate instance names across the two design files, every `excluded_because.difficulty_instance` resolves to a §1.8 name, no stub carries a `test_recipe`, every full instance has all four required keys.
- The only lint failures encountered (7, all "capture JSONPath unresolvable") were field-name drift in §1.9 captures — `designation_status`→`status`, `effectiveness_check_user_id`→`effectiveness_reviewer_user_id`, and non-existent `ingredient_count`/`round_index`. Fixed, plus a swept-up set of prose assertions referencing undeclared fields (`ProductListing.open_serious_event_count`, `active_listing_count`, `inspection_readiness_status`). `SCAFFOLD.yaml` and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` were not modified.
- Hard constraint honored: nothing outside this task's directory and the scaffold-generator skill was read.
- One pre-existing typo left alone in the finalized `SCAFFOLD.yaml` (~line 2189): a state-machine note says `ERR_RECOVERY_EXCEEDS_OUTSTANDING (400)` while §1.4 declares 422. §1.9 asserts follow §1.4 (422).
- Appended a Step 2 entry to the task's `worklog.md`.

Orchestrator verification: all three files parse as YAML; `SCAFFOLD.yaml` top keys start `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules`; the two design files each carry exactly their single required top-level key.

## Step 3: Copy shared files — 2026-09-03T07:01:00.411Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes). No subagent.

## Step 4: Generate PRD — 2026-09-03T07:38:06.809Z

Final state: `workspace/PRD.md`, 535 lines, sections at `## 1. Introduction` (3), `## 2. Global Specifications & System-Wide Principles` (11), `## 3. Business Logic & Workflows` (198), `## 4. Endpoint Definitions` (416), `## 5. Error Code Catalogue` (476). Ends at the last row of the §5 error table — a real section boundary, not mid-sentence.

**Orchestrator decisions during this step (three subagent runs were needed; recorded here because subagent context is discarded on exit):**

1. **Run 4a (full doc-generator) died from an infrastructure API error**, not a generator fault, after emitting §1–§2 (196 lines, ending cleanly at the close of §2.12) and before any of §3/§4/§5. Decision: rather than discard 196 lines of good prose and pay for a full regeneration, resume generation section-by-section with continuation subagents, each given the append-only + chunked-heredoc protocol and the same hard constraints (no DIFFICULTY/CORNER design files, no sibling tasks, no worklog). `head -196 | md5sum` was pinned before each continuation and re-verified after, so §1–§2 is provably byte-identical to what run 4a wrote.
2. **Run 4b appended §3** (9 subsections, lines 198–414). Returned a Contract 2 coverage audit mapping every §1.2 state machine, §1.3 calculation, §1.7 concurrency rule, §1.6 role nuance and business-rule validation in §1.4 to a covering §3 subsection, plus a Contract 3 path-purity grep over lines 198–414 with zero matches, plus an informational Contract 1 sweep reporting all 169 scaffold field names, 56 error ids and 114 enum values present with 0 missing.
3. **Run 4c re-emitted §4 + §5 after a rollback.** The first §4/§5 attempt was written to an over-detailed spec (per-endpoint request bodies, response shapes and per-error meanings, 833 lines total) because the orchestrator's prompt over-specified the format; the subagent correctly flagged the deviation against `prd-bench-doc-generator/SKILL.md`, which mandates a minimal §4 of exactly 4 columns (Method, Path, Description, Authorized Role(s)) with request/response/side-effects deliberately withheld, and a §5 of exactly 2 columns (Error ID, HTTP Status Code) with no trigger conditions. Decision: honour the skill, since an over-detailed §4 both violates house style and materially lowers task difficulty by handing the implementer a spec sheet instead of forcing reconstruction from the §3 narratives — and Contract 1 was already satisfied by §1–§3 alone (audit in item 2), so nothing was lost by shrinking §4. `PRD.md` was truncated back to the 414-line §3 boundary (`head -414`, md5 `744cebec740821ab0f4f359e156a668f`) and §4/§5 regenerated in the mandated minimal form. This is a regeneration of the offending sections, not a hand-patch.

**Audits returned by run 4c:** §4 table column count 4, §5 column count 2, verified mechanically (`awk -F'|'` → 55 four-column rows = 53 endpoints + header + separator; 58 two-column rows = 56 errors + header + separator); no sub-headings in §4, no prose after the §5 table, no audit footer. Endpoint coverage: sorted `METHOD /path` list diffed against SCAFFOLD §1.5 — diff empty, both sides 53, `/cosmetics` prefix and exact scaffold param names (`{id}`, `{inspection_id}`) preserved. Error coverage: sorted `id status` pairs diffed against SCAFFOLD §1.4 — diff empty, both sides 56, which doubles as the id→status match check. Forbidden-term scan (scaffold / benchmark / difficulty / test wording) over the whole file: 0 hits, so the "harder than expert level" difficulty instruction did not leak into the PRD.

**Scaffold inconsistency adjudicated:** SCAFFOLD.yaml carries a stray state-machine note near line 2189 giving `ERR_RECOVERY_EXCEEDS_OUTSTANDING` as 400 while §1.4 declares 422. Resolved in favour of §1.4 (422) in both §3 prose and the §5 table, on the grounds that §1.4 is the authoritative error declaration. Run 4b separately flagged that `outcome_class = PENDING_RESPONSE` and `effectiveness_verdict = INTERIM` are written by state-machine side effects even though those fields' enum constraints list only terminal values plus null; §3 states both explicitly as non-terminal markers.

## Step 5: Generate unit tests — 2026-09-03T09:42:50.171Z

Launched concurrently with Step 6 in a single assistant message, per the skill's isolation requirement: `test_suite/` does not exist when the implementation generator starts, so the impl agent is *physically* unable to read the tests rather than merely instructed not to.

Subagent summary (verbatim):

Generation is complete. Both stages are emitted, verified and frozen.

## Emitted files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2520_cosmetics_facility_registration_product_listing/`)

**Stage 1 — `test_helpers/` (9 files, 2,305 lines)**
`__init__.py` 59 · `api_client.py` 376 · `api_errors.py` 139 · `assertions.py` 224 · `constants.py` 347 · `factories.py` 326 · `fixtures.py` 506 · `test_users.py` 80 · `types.py` 248

**Stage 2 — `test_suite/` (17 test modules + conftest, 8,479 lines)**
`conftest.py` 15 · `test_01_dual_variant_calculations.py` 301/9 tests · `test_02_combinatorial_formulas.py` 239/8 · `test_03_non_linear_state_machines.py` 219/6 · `test_04_transitive_cascades.py` 275/9 · `test_05_validation_priority_conflicts.py` 270/6 · `test_06_boundary_precision.py` 267/7 · `test_07_cross_entity_state_dependency.py` 253/7 · `test_08_resource_temporal_overlap.py` 309/9 · `test_09_compensating_invariants.py` 412/11 · `test_10_entity_defaults_and_reads.py` 626/18 · `test_11_state_machine_transitions.py` 1301/36 · `test_12_derived_calculations.py` 844/25 · `test_13_validation_rules.py` 1200/38 · `test_14_endpoint_contracts.py` 504/15 · `test_15_role_authorization.py` 639/18 · `test_16_layered_complexity.py` 354/9 · `test_17_error_surface.py` 451/12

**Total: 243 tests, 243 `Design:` tags (1 per test, no untagged, no dual-tagged, no orphan tags).**

## Verification
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` → **ALL_COMPILE_OK** (`__pycache__` removed afterwards).
- Citation audit (literal-substring check of every `PRD: "…"` line against `workspace/PRD.md`, plus a "scaffold"-mention scan): **bad 0, total tags 243**.
- Symbol refcheck (every `K./E./F./X./A./api.` name resolves in the frozen helpers): clean on all 17 modules.
- Coverage audit: all **18/18** queue-A instances carry 3–6 tagged tests each (requirement ≥2); all queue-B non-stub instances carry ≥1 (requirement ≥1) except the one deliberate skip below; the **24** `excluded_because` stubs were never translated.

## Coverage ledger
**Queue A (§1.8) — 18/18 translated**, none skipped: dual-variant (5,4), combinatorial (4,4), non-linear state machine (3,3), transitive cascade (4,5), priority-pair conflict (3,3), boundary precision (3,4), cross-entity state (3,4), temporal overlap (4,5), compensating invariant (5,6).

**Queue B (§1.9) — 70 of 71 full instances translated, 1 skipped.**
- `endpoints/transfer_relinks_a_draft_listing_and_moves_exactly_one_designation_slot` — **SKIPPED (PRD-first, condition 2)**: the instance's asserted slot arithmetic contradicts PRD line 310, where the designation cap on a transfer is evaluated against the **incoming** designee and the outgoing designee's count decrements; the yaml's outcome is not uniquely derivable. Gap left as a gap, no placeholder emitted.

## Yaml-vs-PRD adjudications applied (assertions weakened only where the yaml, not the PRD, was wrong)
- `ERR_RECOVERY_EXCEEDS_OUTSTANDING` asserted at **422** (§1.4/PRD), not the stray 400 note; `PENDING_RESPONSE` and `INTERIM` treated as legal non-terminal markers, per instruction.
- Withdrawal/recall "INITIATED" in the yaml mapped to the PRD's `OPEN` / `PLAN_REQUIRED`.
- `records_production_is_atomic_across_three_records`: three same-lot windows re-spaced to disjoint days (the PRD refuses touching windows per `lot_code`).
- `clock_endpoint_reports_the_instant_it_replaced`: dropped the "plain object, no id/version envelope" assertion (not uniquely derived); no-op evidenced by an empty facilities collection.
- `reclassification_is_a_shared_operation_for_reviewer_and_agent`: the yaml's reviewer **downgrade** contradicts "raised at most once and never lowered" — replaced by each permitted role raising one RETAINED event (counter 2, not the yaml's 1).
- `the_reviewer_who_screened_the_dossier…`: score is **1.50**, not the yaml's 5.00 (5 × 0.3 OTHER credential factor, both modes); no post-resubmission `review_mode` assertion.
- `sweep_is_a_checkpoint…`: dropped the `entry_type=SWEEP_TRANSITION` ledger assertion — no such entry type exists in the PRD's nine-value vocabulary; replaced by a byte-for-byte ledger comparison across the repeat sweep.
- `malformed_payloads_all_collapse_to_invalid_request`: the yaml's "rejected before the listing id is even resolved" inverts §2.8 (existence is group 3, schema group 5), so the wrong-scalar case is posted against a **real** listing.
- `the_late_report_response_already_carries…`: `POINTS_CHANGE` is not a PRD ledger entry type — replaced by the one `ADVERSE_EVENT_REPORT` entry against the event plus the absence of any `POSTURE_CHANGE` entry (6.50 < 10.00 leaves the dial at `OPEN`).
- Standing: `GET /cosmetics/withdrawals/{id}/recovery-entries` assertions always dropped (endpoint absent from the PRD); yaml full-timestamp date fields passed as `YYYY-MM-DD`.

## Step 6: Generate implementation — 2026-09-03T09:42:50.171Z

Subagent summary (verbatim):

Verification is complete. Task 2520's implementation is finished, compiles, boots, and passes a full end-to-end behavioral smoke test.

## Boot test
Booted with `PORT=18525 bash start.sh` (foreground `exec python3 app.py`, binds `0.0.0.0`), probed, then killed. No task-2520 process of mine is left running (the one live server now under that directory is the concurrent test-suite agent's harness launching `start.sh` per test — which itself confirms the launcher works under `--isolation per-test-server`).

Envelope / error shapes confirmed live:
- `GET /cosmetics/facilities` → 200, `{"data":[],"meta":{...,"has_more":false,"limit":10,"offset":0,"total_count":0},"response_type":"array"}`
- invalid body → 400 `ERR_INVALID_REQUEST`; missing headers → 401 `ERR_UNAUTHENTICATED`; wrong role → 403 `ERR_FORBIDDEN_ROLE`; unknown route → 404 `ERR_NOT_FOUND`; bad method → 405 `ERR_METHOD_NOT_ALLOWED`; malformed JSON → 400 `ERR_INVALID_REQUEST`
- `api_request_timestamp` is `2026-08-01T00:00:00.000Z` on a fresh process, proving the logical clock default and that nothing is seeded (`total_count: 0` on every collection at boot).

## End-to-end smoke test (69 assertions, all matching the PRD)
A 76-request scenario driven through the real HTTP API: facility create → submit → approve (`FEI-000001`), RP create, listing + ingredient, dossier + 2 evidence items → submit → FULL review (`adequacy_score` 65.00, `ADEQUATE`), listing submit → LIST (`CPL-000001`, `marketable` true), distribution record, overlapping-lot rejection (`ERR_LOT_WINDOW_CONFLICT` 409), recall → plan → accept, stale-OCC rejection (`ERR_STALE_RECALL_VERSION` 412), withdrawal, records-production, over-cap recovery (`ERR_RECOVERY_EXCEEDS_OUTSTANDING` **422**, per adjudication 1), verified return, segregation-of-duties block (403), effectiveness check (provisional 89.67 → credit 3% → denominator 1455 → final 92.44 → `EFFECTIVE`, recall `CLOSED_EFFECTIVE`), adverse event (deadline `2026-08-16T23:59:59.999Z`), clock set, compliance sweep (1 overdue, 1 revalidation, idempotent on re-run), late filing (10 days, 10.00 points), and a gap-free ledger `[1..10]` with the prescribed entry ordering.

One assertion initially "failed" and turned out to be my test expectation, not the code: I expected `serious_event_points` 17.10 after the sweep, got 18.00. PRD §"How an event becomes points" gives 17.10 only for a **9**-day overdue event (9 × 1.9); this scenario is 10 days overdue by the normative ceil-divide rule, so 9 × 2.0 = 18.00 is correct. No code change was needed.

## Files
`/home/ubuntu/github/CodingPRD/tasks/task_2520_cosmetics_facility_registration_product_listing/workspace/implementation/`

| file | lines |
|---|---|
| domain.py | 1028 |
| routes/facilities.py | 517 |
| routes/recalls.py | 448 |
| routes/listings.py | 446 |
| routes/substantiations.py | 247 |
| calc.py | 212 |
| store.py | 212 |
| access.py | 203 |
| schema.py | 187 |
| routes/events.py | 167 |
| errors.py | 135 |
| routes/ops.py | 117 |
| envelope.py | 92 |
| app.py | 82 |
| routes/persons.py | 55 |
| routes/__init__.py | 1 |
| **total .py** | **4149** |

Plus `start.sh` (executable, reads `$PORT`, guarded pip install, `exec` in foreground) and `requirements.txt` (`flask>=2.0`). `python3 -m py_compile` passes on all 16 modules; `__pycache__` removed.

## Compliance with the hard constraints
- Storage is in-memory dicts only — a grep for `sqlite3|json.dump|open(|/tmp|pickle|shelve` across all modules returns nothing, so `start.sh` re-invocation wipes all state.
- No entity is seeded, preloaded or hardcoded; every collection is empty at boot.
- Endpoint coverage is 53/53 against the scaffold table (programmatic diff: no missing, no extra routes).
- Rejection precedence runs through one shared rank-sorted pipeline (`access.Checks`, 56 rank constants mapped 1:1 onto PRD §2.8), not per-endpoint ad-hoc ordering.
- Adjudication 1 honored (`ERR_RECOVERY_EXCEEDS_OUTSTANDING` = 422, verified live). Adjudication 2 honored (`outcome_class = PENDING_RESPONSE`, `effectiveness_verdict = INTERIM` are legal non-terminal values).
- Withheld files were not read: no `test_suite/`, `test_helpers/`, `SCAFFOLD_*_DESIGN.yaml`, `worklog.md`, or sibling `task_*/` directory was opened.

One implementation note worth passing on: `reversal_target_bucket`'s value domain is specified by neither the PRD nor the scaffold, so `domain.resolve_bucket_field` accepts both spellings — the movement kind (`REPORTED_RETURN`) and the record's own field name (`units_reported_returned`).

Orchestrator verification: `test_helpers/` 9 files, `test_suite/` 17 modules + conftest totalling 243 `def test_` functions (matches the subagent's count), `workspace/implementation/` with `start.sh`, `requirements.txt`, `routes/` and 11 top-level modules.

## Step 7: Run tests and iterate — 2026-09-03T10:13:00.000Z

Subagent summary (verbatim):

All 8 parallel rounds green at 243/243. Exiting.

## Summary

**Iterations run:** 3 (iteration 1 = baseline diagnosis at 221/243 × 8; iteration 2 = fixes applied, 7/8 rounds clean + 1 boot-race artifact; iteration 3 = confirmation, 8/8 clean).

**Baseline:** 22 failures, identical in all 8 rounds — no flakiness. They collapsed into only 3 root causes.

**Tests deleted:** none. One assertion removed under STEP 1c partial-coverage split:
- `test_suite/test_13_validation_rules.py` — `TestSubmissionDemandsAnAdequateDossier::test_a_failed_submission_is_not_a_partial_transition` dropped `assert listing["submitted_at"] is None` (**PRD-silence: computed/attribute-field silence**). PRD never gives `ProductListing` a `submitted_at`; §3.3's listing-defaults sentence enumerates its initial fields and omits it, and every PRD occurrence of `submitted_at` belongs to `AdverseEvent` (as do the scaffold's, line 640). Adding the field to the implementation would have violated the "no response field without a verbatim PRD sentence" rule. The test's PRD-covered assertions (`listing_status` DRAFT, `safety_status` SUBSTANTIATION_FAILED, `listed_product_count` 0) were kept.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper was constructing a PRD-inconsistent precondition.

**Fixes applied to `implementation/`:**
1. `store.py` — `iso()` now omits the fractional part when an instant carries no sub-second component, and a new `iso_ms()` always renders three digits. This was the single root cause of **19 of the 22 failures**. PRD §2.5 pins the clock's rendering verbatim ("the logical clock reads exactly `2026-08-01T00:00:00Z`"), and three fractional digits are mandated *only* for the §2.4 audit columns and the §2.2 `api_request_timestamp` — never for clock-echoed or client-supplied domain instants (`current_utc`/`previous_utc`, `swept_at`, `occurred_at`, `received_at`, `filed_at`, `submitted_at`, `reclassified_at`, `plan_submitted_at`, `response_submitted_at`, `decided_at`). Derived deadlines still render `.999Z` because `end_of_day` carries a non-zero microsecond.
2. `store.py` (`insert`, `touch`), `envelope.py` (`_meta`), `routes/substantiations.py` (review-item `updated_at`) — switched to `now_iso_ms()` so §2.2/§2.4 keep their mandated three digits. This also preserves fixed-width `created_at` strings, which `by_created`/`by_created_desc` sort lexicographically.
3. `routes/facilities.py` (`list_periods`) — applied the `status` query filter, which was being ignored entirely, per §3.1 "the listing may be narrowed with a `status` filter."

**Note on the codebase idiom:** `routes/facilities.py` imports `request` function-locally rather than at module scope; my first cut at fix 3 omitted the local import and turned the endpoint into a 500. Caught by smoke test before the sweep, not by the sweep.

**Round 7 of iteration 2** failed one test (`test_the_catch_up_filing_lowers_the_price_and_de_escalates`) on `RemoteDisconnected` at its very first `POST /cosmetics/facilities`, immediately after the runner logged "Restarting API server" — a server-boot race under host load, not a defect (no `Terminated` in the log, so not reaping; the same test passed in the other 7 rounds). Confirmed load-induced by the clean iteration-3 sweep rather than "fixed".

**Final sweep evidence:** results.1 243/243 · results.2 243/243 · results.3 243/243 · results.4 243/243 · results.5 243/243 · results.6 243/243 · results.7 243/243 · results.8 243/243 — union of failures across all 8 rounds: 0.

**Orchestrator independent verification** (not taken on the subagent's word — a Step 7 agent can report a clean sweep while leaving no artifacts behind): all 8 `workspace/implementation/results.{1..8}.json` exist on disk, ~84.8 KB each, written 10:13, and re-parsing each with `json.load` gives `passed=243, failed=0, total=243` for every round. ALL GREEN.

Step 8 is therefore NOT skipped: Step 7 applied 4 `implementation/` fixes across 4 files and removed one assertion, so `PRD.md` did not uniquely determine every behavior the implementation exhibits.

## Step 8: Finalize PRD — 2026-09-03T10:18:02.453Z

Subagent summary (verbatim):

`PRD_FINALIZED.md` is produced at `/home/ubuntu/github/CodingPRD/tasks/task_2520_cosmetics_facility_registration_product_listing/workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 535 lines
- `PRD_FINALIZED.md`: 537 lines (+2 lines, **+0.37%**) — one inserted paragraph plus its blank separator. No existing line altered or removed.

## Changes
- **§2.5 — insert — pins the two timestamp-rendering shapes**: `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2) always carry three fractional digits; every other rendered instant omits the fractional part when it has no sub-second component and shows three digits (truncated, not rounded) when it does — `implementation/store.py:33-60` (`iso`/`iso_ms`), `store.py:184,210,213`, `envelope.py:28`.

That is the **only** edit. The other two `<step_7_diff>` items required none:
- **Fix 3 (`list_periods` status filter)** — `routes/facilities.py:225-227` now applies an exact-string `status` filter, ignored when blank, matching every other list filter in the codebase. PRD §3.1 already states verbatim "the listing may be narrowed with a `status` filter", so this was a pure implementation bug against an already-determined PRD sentence. Prose kept verbatim.
- **Deleted assertion (`listing["submitted_at"]`)** — the implementation has no `submitted_at` on `ProductListing` (`domain.py:590-613` carries none; every `submitted_at` in the impl belongs to `AdverseEvent`, `routes/events.py:66`, `domain.py:682`). PRD never mentions such a field, so a fresh implementer would not create one. Nothing to pin; adding a sentence would have invented a field.

## Per-edit pre-edit search log

**Edit 1 — §2.5 timestamp rendering**

(a) **Subject identified:** how the service renders any instant-valued response field — i.e. the choice between fixed-3-digit and variable-precision ISO-8601 output, and which fields take which.

(b) **Impl paths enumerated (grepped/read):**
- `store.py` — `iso()` (variable), `iso_ms()` (always 3), `now_iso()`, `now_iso_ms()`, `iso_date()` (date-only), `end_of_day()` (microsecond `999000`, which is why derived deadlines print `.999Z`).
- Exhaustive grep of `iso|iso_ms|now_iso|iso_date|end_of_day` and of every `"*_at":` key across `store.py`, `envelope.py`, `domain.py`, `calc.py`, `schema.py`, `access.py`, `errors.py`, `app.py` and all seven modules under `routes/`.
- **`iso_ms` callsites (fixed 3 digits):** `store.insert` → `created_at` for all 14 kinds including `ledger` (`common=False`); `store.touch` → `updated_at`; `envelope._meta` → `api_request_timestamp`; `routes/substantiations.py:229` → review-item `updated_at`.
- **`iso`/`now_iso` callsites (variable):** `routes/ops.py:33,34` `current_utc`/`previous_utc`; `routes/ops.py:116` `swept_at`; `domain.py:501` ledger `occurred_at`; `domain.py:560,561` `filed_at`/`filing_deadline_at`; `domain.py:648` `decided_at`; `domain.py:675,679,680,681,682` `received_at`/`deadline_basis_at`/`deadline_at`/`reclassified_at`/`submitted_at`; `domain.py:708,709` `response_due_at`/`response_submitted_at`; `domain.py:727,729` `plan_submitted_at`/`plan_decision_at`.
- **Deadline producers confirmed `.999Z`:** `routes/events.py:28`, `routes/facilities.py:259`, `routes/facilities.py:486` — all via `end_of_day`.
- **`iso_date` (date-only, must not be swept into an "instant" claim):** facility/period bounds, `renewal_window_open_date`, `grace_end_date`, `change_effective_date`, `retention_until`, `window_start`/`window_end`, `ship_date`/`delivery_date`.
- **Withdrawal serializer (`domain.py:735-757`) confirmed to hold no instant field** beyond the audit columns; ownership-change serializer confirmed to have no `decided_at`.
- `schema.instant_field` / `store.parse_instant` — accepts `%f`, and both renderers use `microsecond // 1000`, i.e. sub-millisecond input is truncated.

(c) **Wording adjustments made:** (1) Phrased the field list as "**including** …" behind the universal rule "Every other instant the service renders", so the enumeration cannot be read as a closed set that excludes an instant Step 7 never exercised. (2) Scoped the sentence to *instants* only and dropped a drafted clause about `YYYY-MM-DD` fields, so none of the 12 `iso_date` fields is mis-described (and §2.5's next paragraph already covers them). (3) Added "any finer precision in a client-supplied value being truncated rather than rounded" after confirming both `iso` and `iso_ms` use integer division — without it a fresh implementer could legitimately round. (4) Used "an instant taken from a logical clock standing on a whole second" rather than naming a specific field, keeping the example true for `current_utc`, `swept_at`, `occurred_at`, `filed_at`, `submitted_at`, `decided_at`, `plan_submitted_at`, `plan_decision_at` and `response_submitted_at` alike, and consistent with §2.5's pre-existing verbatim `2026-08-01T00:00:00Z`.

Orchestrator verification: `PRD_FINALIZED.md` is 537 lines vs `PRD.md`'s 535, md5s differ (`2b5d88eb…` vs `7bd3e3e3…`), and `diff` shows exactly one hunk — an insert of the timestamp-rendering paragraph plus its blank separator after line 103. No deletions, no rewrites.

## Step 9: Complete PRD — 2026-09-03T10:56:36.557Z

**Orchestrator decision: Step 9 was run as three sequential file-partitioned passes over a single shared `PRD_COMPLETED.md`, not as one subagent.** A single agent asked to "walk implementation/ exhaustively" across 4149 lines in 16 modules reliably degrades into a skim, and its characteristic failure signature is a `PRD_COMPLETED.md` byte-identical to its source — i.e. the scan never actually ran. Partitioning by implementation file makes each slice small enough to read line by line, and running the passes sequentially (never concurrently) avoids lost-update races on the one output file. Each later pass was given an explicit inventory of what the earlier passes had already pinned, so the passes neither duplicated nor contradicted each other, and pass C additionally owned a whole-document coherence read.

Partition used:
- **Pass A — cross-cutting infrastructure**: `app.py`, `envelope.py`, `errors.py`, `schema.py`, `access.py`, `store.py`. Owned Step 0 (`cp PRD_FINALIZED.md PRD_COMPLETED.md`). Result: 537 → 540 lines, **11 ambiguity-pins + 1 mismatch-revision**. Pinned identity-header trimming, the full ownership-resolution chains, `api_request_id` = `req_` + 20 uppercase-alnum chars, the error envelope covering 5xx as well as 4xx (mismatch), pagination edge semantics, the list sort tie-break being insertion sequence, `version` rising exactly once per request even across cascade hops, accepted instant/date *input* spellings, what counts as a schema violation, `contact_email` shape, and router-level `ERR_NOT_FOUND`/`ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL` (three rows appended to §5). Verified clean: all 56 catalogued error ids and statuses match `errors.py` one for one, and the 56 rank constants in `access.py:16-71` reproduce §2.8's order group for group.
- **Pass B — domain core**: `calc.py`, `domain.py`. Result: 540 → 540 lines (all in-paragraph), **15 ambiguity-pins + 7 mismatch-revisions**. Notable mismatches corrected: the four mirrored period dates are written only when a period is minted and never cleared (so they keep showing an `EXPIRED` period's dates after a lapse — §3.1's "all four are null whenever no period is `ACTIVE`" was false); `abbreviated_renewal_eligible` is derived on every read rather than stored false by an accepted filing; `gmp_readiness_score`/`last_inspection_outcome` are written where they arise, never recomputed from the collection, so the two may name different engagements; step 1 of the sweep requires `current_period_end` not yet passed for the `RENEWAL_DUE` branch. Also pinned JSON rendering of two-decimal quantities (`100.00` → `100.0`), several ledger-order footprints, withdrawal null-not-zero opens, `reversal_target_bucket`'s two accepted spellings, discarded `decision_note`/`reason` fields, and the evidence-item `version` exception. Verified clean: `calc.py` pinned end to end (all weights, tiers, caps, rounding boundaries and inclusive pass marks), all 13 serializers checked field by field in both directions (every emitted key appears in the PRD; all 189 backticked snake_case PRD identifiers exist in the implementation).
- **Pass C — route modules**: all 8 files under `routes/`, all 53 endpoints. Result: 540 → 540 lines, **14 ambiguity-pins + 6 mismatch-revisions**. Notable mismatches corrected: `FEI-`/`CPL-` ordinals are minted as one greater than the count of resources already carrying a number (order of approval/issuance), NOT as a position in a `created_at` ordering as §3.1 and §3.5 both claimed — these diverge as soon as a number is skipped; a renewal filed from `LAPSED` appends no "renewal accepted" `STATE_TRANSITION`; a recovery entry names one `distribution_record_id`, not several; `gmp_readiness_score` is stored at issuance on both fork branches and `last_inspection_outcome` takes `NAI` at issuance; and §4's intro now carries a response-**body** rule alongside the status-code rule (201 creates carry the newly minted child; every other success is 200 with the resource the path names last; the recovery post is the single documented departure, answering 201 with the distribution record). Also pinned the two system-wide collections (`GET /listings`, `GET /distribution-records`) authorizing all five roles with no ownership check — previously a live contradiction of §2.1 — and the uniform "filter applied only when non-empty" discipline.

Cross-pass contradiction found and resolved: pass B's §3.7 mirror sentence said `last_inspection_outcome` moves only on `VAI`/`OAI`, which contradicted §3.7's own issuance paragraph and the implementation; pass C revised it. Pass C's final coherence read confirmed no remaining contradiction, that the §4 table's 53 rows and authorized-role lists match every `access.authorize(...)` call, and that every `return envelope.*` site matches the new §4 rule.

**Totals across the three passes: 40 ambiguity-pins + 14 mismatch-revisions = 54 changes**, touching 91 lines relative to `PRD_FINALIZED.md`.

**Orchestrator verification:** `PRD.md` 535 lines (md5 `7bd3e3e3…`), `PRD_FINALIZED.md` 537 lines (`2b5d88eb…`), `PRD_COMPLETED.md` 540 lines (`0b5afc9e…`) — three distinct md5s, so neither derived file is a byte-identical copy of its source, and `diff PRD_FINALIZED.md PRD_COMPLETED.md` reports 91 changed lines. `PRD_COMPLETED.md` retains all five top-level sections (§1 line 3, §2 line 11, §3 line 200, §4 line 418, §5 line 478) and ends at a real section boundary — the last row of the §5 error table (`ERR_INTERNAL | 500`), no truncation, no audit footer.

**Test status still green at pipeline exit:** Step 9 edits documentation only. `find implementation test_suite test_helpers -name '*.py' -newermt '2026-09-03 10:13'` returns nothing, i.e. no implementation or test file was modified after the green sweep, so the Step 7 evidence (8/8 rounds at 243/243, `results.{1..8}.json` on disk and independently re-parsed by the orchestrator) remains valid for the artifacts as shipped.

## Pipeline complete — 2026-09-03T10:56:36.557Z

All nine steps done. Deliverables: `SCAFFOLD.yaml` (3404) + `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1735) + `SCAFFOLD_CORNER_DESIGN.yaml` (4749); `test_helpers/` (9 files, 2305 lines) + `test_suite/` (17 modules + conftest, 8479 lines, 243 tests, 0 deleted); `workspace/implementation/` (16 modules, 4149 lines + `start.sh` + `requirements.txt`, 53/53 endpoints); `workspace/PRD.md` (535) → `PRD_FINALIZED.md` (537) → `PRD_COMPLETED.md` (540); `workspace/implementation/results.{1..8}.json` all 243/243.
