# Worklog — task_2620_domain_name_dispute_resolution

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2620_domain_name_dispute_resolution` and `.../workspace` (pre-assigned path from the orchestrator invocation; no index auto-allocation performed, per instructions — other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T22:57:00.000Z

Subagent summary (verbatim):

Task 2620 scaffold is complete and lint-clean.

**Final work done this pass** — closed the last audit gap (two §1.5 endpoints that no §1.8/§1.9 call exercised), both in `/home/ubuntu/github/CodingPRD/tasks/task_2620_domain_name_dispute_resolution/SCAFFOLD_CORNER_DESIGN.yaml`:

- `GET /udrp/decisions/{id}/votes` added to the §1.9 `endpoints` instance `publication_assembles_its_own_digest_and_the_precedent_filters_narrow_the_page` (as `Panelist`, `payload: {}`, collection captures `$.meta.total_count` / `$.data[0].{seat,vote,rdnh_vote,voter_panelist_id,rationale}`), plus a matching assert that publication redacts the precedent entry but never the immutable ballots, and a new ground `endpoints[GET /udrp/decisions/{id}/votes].output`.
- `GET /udrp/decisions/{id}/court-challenges` added to the §1.9 `state_machines` instance `dismissed_challenge_lifts_the_stay_and_restarts_the_full_waiting_period`, deliberately placed *after* the refused second `resolve`, so its assert (`total_count 1`, `status DISMISSED`, `resolved_at 2026-08-25T12:00:00Z`, `filed_by RESPONDENT`, docket unchanged) also proves the rejected SUSTAINED resolve wrote nothing.

**Verifications**
- Endpoint coverage audit now reports `unmatched calls: set()` and `total endpoints: 53 exercised: 53` (previously 51/53).
- Linter verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    53
  §1.1 entities declared:     16
  §1.8 instances scanned:     28
  §1.9 instances scanned:     47
  Calls scanned (§1.8+§1.9):  1551

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

- Forbidden vocabulary: none in any of the three files. Unbound `${var}` placeholders: none in either design file. All three parse under PyYAML; `SCAFFOLD.yaml` carries neither design key, and each design file has exactly its one top-level key.
- Final sizes: `SCAFFOLD.yaml` 3500 lines, `SCAFFOLD_DIFFICULTY_DESIGN.yaml` 4394, `SCAFFOLD_CORNER_DESIGN.yaml` 4585, each ending at a real YAML boundary.
- §1.9 shape: nine sections in guide order — entities 14, state_machines 14, calculations 13, validations 10, endpoints 6, errors 2, rbac 7, cross_cutting_complexity_layers 5, consistency_model 1 — i.e. 47 real instances plus 25 `excluded_because:` stubs. §1.8 holds the full 28 instances.

No sibling task directory was read at any point.

Orchestrator verification: all three files present (3500 / 4394 / 4585 lines).

## Step 3: Copy shared files — 2026-09-03T22:58:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T23:16:00.000Z

Subagent summary (verbatim):

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2620_domain_name_dispute_resolution/workspace/PRD.md` — **435 lines / 94 KB**, written in five incremental heredoc appends plus three small targeted edits (no one-shot write). Final section heading is `## 5. Error Code Catalogue`; the document ends at a real boundary with the last catalogue row `` | `ERR_CHALLENGE_WINDOW_CLOSED` | 409 | `` and no audit footer.

**Structure:** §1 Introduction (3 paragraphs) · §2 with 10 domain-derived subsections (2.1 Actors/Authentication/Segregation of Provider Duties, 2.2 API Response Structure copied byte-identical from `section-2.2-response-structure.md`, 2.3 Pagination, 2.4 Logical Clock/Holiday Calendar/Deadline Sweep, 2.5 Docket Identity, 2.6 Case-Rooted and Nested Paths, 2.7 Version Pinning, 2.8 Money/Cents/Rounding, 2.9 Cascade Integrity and Running Counters, 2.10 The Order of Refusal — a 14-band precedence ladder) · §3 with 9 subsections (docket build-out → filing/pricing → ledger/withdrawal → compliance review + correction loop + registrar verification → notification/response window → panel constitution → deliberation/tally/issuance → waiting period/challenge/execution → publication/precedent) · §4 a 4-column, 53-row endpoint table · §5 a 2-column, 50-row error table.

**Hard Contracts**

```
Field coverage check:
- entities[].fields: 150 required, 150 present, 0 missing
- endpoints[].request_body: 85 required, 85 present, 0 missing
- endpoints[].query_params: 13 required, 13 present, 0 missing
Status: PASS
```
(161 unique names after dedup; two verification passes — pass 1 surfaced `decision_id` only, which was added to the ballot paragraph in §3.7; pass 2 clean.)

```
Rule coverage check:
- validations[] with priority: 50 checked, 50 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_case_version + ERR_STALE_CASE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 44 checked, 44 fully expressed, 0 missing
- calculations[]: 15 checked, 15 fully expressed, 0 missing
- validations[] conditions: 50 checked, 50 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 53 endpoints checked, all side-effect items expressed, 0 missing
- entities[].fields[] structured content: 150 checked, 150 reconstructible from prose, 0 missing
- sibling-branch symmetry: 9 groups checked (fee variants, deadline variants, screening bands, refund percentage tiers, replacement source states, tally limbs, court dispositions, redaction levels, execution outcomes), 9 with equal prose density, 0 asymmetric
Status: PASS
```

```
§3 Path Purity check: 0 backtick tokens in §3 start with "/", 0 are bare HTTP methods, 0 combine method+path, 0 embed the /udrp prefix.
Status: PASS
```

**Key findings worth flagging to the pipeline owner (both handled, neither invented):**
- The scaffold is internally inconsistent twice. (1) `Case.required_seat_count` is *computed* as 3 when either election is `THREE`, but `POST /udrp/cases`'s side effects say it is created at 1 and the provisional fee variant "forces seat_count to 1". The PRD renders the computed rule as the field definition and states separately that the provisional assessment always *prices* a single-member panel, which keeps both scaffold statements true. (2) `DomainName.locked_at` is described as "never cleared afterwards", but both the `LOCKED → UNLOCKED` transition and the lock endpoint say `locked_at -> null`; the PRD follows the two mechanism statements (cleared on release).
- `PanelistAppointment` side effects reference a `discharged_at` stamp, but no such field exists in the entity. The PRD expresses discharge timing without naming a stored field, so no phantom field enters the test surface.
- `POST /udrp/registrars` never accepts `lock_sla_hours` even though the field exists with a default of 24; the PRD carries it as an audit-only registrar attribute enforced by no gate.

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was read.

Orchestrator truncation check (mandated by the invocation): `wc -l` = 435; tail ends on a complete markdown table row at the end of `## 5. Error Code Catalogue`, not mid-sentence; all five top-level sections present in order. Cross-checked error-id coverage independently: 50 distinct `ERR_*` ids in PRD.md vs 51 in SCAFFOLD.yaml, the single difference being `ERR_XXX`, which is a spec placeholder token in the scaffold, not a real error. PRD accepted, no regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T01:45:00.000Z

Subagent summary (verbatim):

The unit-test suite for `task_2620_domain_name_dispute_resolution` is complete.

## Output

**`/home/ubuntu/github/CodingPRD/tasks/task_2620_domain_name_dispute_resolution/test_helpers/`** (Stage 1 — 2002 lines)

| file | lines |
|---|---|
| `__init__.py` | 44 |
| `api_client.py` | 197 |
| `api_errors.py` | 113 |
| `assertions.py` | 237 |
| `constants.py` | 97 |
| `factories.py` | 219 |
| `fixtures.py` | 585 |
| `test_users.py` | 64 |
| `types.py` | 446 |

**`/home/ubuntu/github/CodingPRD/tasks/task_2620_domain_name_dispute_resolution/test_suite/`** (Stage 2 — 6953 lines, **110 tests**)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 45 | — |
| `test_01_fee_and_deadline_variants.py` | 216 | 7 |
| `test_02_conflict_scoring_and_honoraria.py` | 257 | 6 |
| `test_03_looping_and_forking_state_machines.py` | 354 | 6 |
| `test_04_cascades.py` | 401 | 6 |
| `test_05_refusal_precedence_pairs.py` | 342 | 6 |
| `test_06_boundary_instants.py` | 324 | 6 |
| `test_07_cross_entity_gates.py` | 380 | 6 |
| `test_08_scarce_resource_intervals.py` | 466 | 8 |
| `test_09_conserved_totals.py` | 403 | 6 |
| `test_10_reference_registers.py` | 642 | 13 |
| `test_11_lifecycle_paths.py` | 666 | 9 |
| `test_12_derived_values.py` | 332 | 3 |
| `test_13_validation_ladders.py` | 531 | 7 |
| `test_14_endpoint_behaviours.py` | 402 | 7 |
| `test_15_error_envelopes.py` | 251 | 3 |
| `test_16_authorization.py` | 382 | 6 |
| `test_17_layered_interactions.py` | 417 | 4 |
| `test_18_read_after_write.py` | 142 | 1 |

## Design-index coverage

- **Queue A — `SCAFFOLD_DIFFICULTY_DESIGN.yaml` §1.8: 28 instances, 28 live, 28 translated, 0 skipped.** Every one carries >=2 tests (files 01-09).
- **Queue B — `SCAFFOLD_CORNER_DESIGN.yaml` §1.9: 72 instances, 25 stubs (`excluded_because`), 47 live, 47 translated, 0 skipped.** Sections: `entities` 13, `state_machines` 9, `calculations` 3, `validations` 7, `endpoints` 4, `errors` 2, `rbac` 4, `cross_cutting_complexity_layers` 4, `consistency_model` 1.
- **Nothing was skipped for PRD-coverage failure** — every live instance survived the two-condition filter. No stub instance was tagged.

## Verification run

- Tag audit: 110 tests, every docstring ends with exactly one `Design:` line, every tag resolves to a real `name:` in one of the two design YAMLs, no dual tags, no untagged tests. **0 problems.**
- Verbatim-citation grep against a whitespace-normalised `workspace/PRD.md`: every quoted fragment matched. **0 problems.**
- Section-label check: every `PRD §X:` label resolves to a real PRD header and the quoted sentence lies inside that section's line range. **0 problems.**
- `ast.parse` over all 28 files: clean. Every `from test_helpers import ...` name resolves; no unused imports.

## Notable resolutions in this final pass

- **`test_17` / `an_unnamed_replacement_...`**: PRD §3.3 line 186 ("Inflows are positive and refund lines are negative") and §3.4 line 204 ("the negative of that amount") override the corner YAML's assertion text "a REFUND of 150000" — the test asserts `amount_cents == -150000`.
- **`test_18` / `derived_fields_and_counters_...`**: the YAML asserts "the nomination response already carries `decision_due_at`". PRD §3.6 line 262 sets `decision_due_at` only at the transition into `ACCEPTED`, so that sub-assertion is not PRD-derivable and was dropped; the test asserts only `conflict_score is None` and `honoraria_cents == 0` on the `NOMINATED` row, then proves `decision_due_at` appears in the screening response.
- `setup_issued_single_member_decision` cannot forward a ballot `rationale`, so `test_14` hand-builds its issued-decision chain instead.

No file was written under `workspace/`; `workspace/implementation/` was never read.

Orchestrator verification: `test_helpers/` and `test_suite/` both at the task root (NOT under `workspace/`) — the known misplacement failure did not occur. 19 files in `test_suite/`, 110 `def test_` functions counted independently. `__pycache__` dirs removed.

## Step 6: Generate implementation — 2026-09-04T00:03:00.000Z

Launched concurrently with Step 5 in a single assistant message, so `test_suite/` did not exist when the implementation generator started (physical isolation from the tests).

Subagent summary (verbatim):

Implementation complete and verified. Smoke servers on ports 39177 and 41855 were both killed by exact PID (never by name pattern); both ports confirmed closed.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2620_domain_name_dispute_resolution/workspace/implementation/`)

| file | lines |
|---|---|
| `routes/cases.py` | 586 |
| `services/logic.py` | 409 |
| `routes/decisions.py` | 381 |
| `routes/registry.py` | 276 |
| `services/calc.py` | 263 |
| `routes/panel.py` | 242 |
| `validate.py` | 198 |
| `db.py` | 161 |
| `errors.py` | 116 |
| `response.py` | 64 |
| `app.py` | 56 |
| `middleware.py` | 42 |
| `start.sh` | 10 (chmod +x) |
| `requirements.txt` | 1 |
| `routes/__init__.py`, `services/__init__.py` | 0 |
| **total** | **2805** |

All `.py` files pass `python3 -m py_compile`. `__pycache__` dirs removed.

## Endpoint coverage: 53 / 53

A regex diff of every `@bp.<verb>("path")` against every `| VERB | \`path\` |` row in the PRD §4 table gives 53 implemented, 53 specified, with an empty symmetric difference — no missing routes and no extras.

## Verification

Fresh boot is clean and stateless: `GET /udrp/cases` on a virgin process returns `total_count: 0` and the logical clock reads exactly `2026-08-01T00:00:00.000Z`; storage is Python dicts only, nothing is seeded, and no file/SQLite/tmp artifact is written — so `--isolation per-test-server` re-launch is safe. Unknown routes return `ERR_RESOURCE_NOT_FOUND`.

A full end-to-end lifecycle smoke test passed with all PRD worked examples reproduced exactly:
- Filing: `D-2026-000001`, sole-panelist pricing 150000 / 150000 / 105000.
- Clearance -> verification `due_at` = requested + 48h; registrar answer -> `RESPONDED`.
- POSTAL notification: allowance 5 days, `PROVISIONAL` due 2026-08-26.
- Three-member election re-prices to 400000 assessed / 275000 complainant / 125000 respondent / 280000 pool, variant `FINAL`.
- Nomination before the supplement is paid -> 402 `ERR_PANEL_SUPPLEMENT_UNPAID`; after payment three seats nominate.
- Conflict score 34.5 with factors `["PRIOR_APPOINTMENTS","PRIOR_REPRESENTATION"]` -> `WAIVER_PENDING`; waivers -> `ACCEPTED`, panel `PANEL_CONSTITUTED`, honoraria waterfall 112000 / 84000 / 84000 (remainder to the presiding seat, sums to the 280000 pool).
- Draft, three ballots, issue -> `COMPLAINT_DENIED`, `STRICT_MAJORITY`, `dissent_present: true`, `rdnh_finding: true`, complainant `adverse_rdnh_findings` incremented to 1, implementation deadline 10 business days out.
- Publish -> digest `D-2026-000001 | COMPLAINT_DENIED | rdnh=True`, citable; precedent search returns it.
- Court challenge -> `STAYED`; `DISMISSED` resolution restarts the full window from `resolved_at`.
- Implement: wrong registrar -> 403 `ERR_REGISTRAR_MISMATCH`; registrar of record -> `IMPLEMENTED`, lock released for a denial, case closed with `refiling_bar_until` = +30 days, complainant `open_case_count` and panelist `active_case_load` both decremented to 0.
- Both deadline sweeps returned all four counters at 0 (idempotent); `POST /udrp/_clock/set_current_utc` returns `{}`.

## PRD ambiguities resolved

1. **§3.8 business-day worked example contradicts its own algorithm.** The prose says a decision issued Friday 2026-08-28 implements on Friday 2026-09-11, but 10 business days excluding the anchor day and skipping the 2026-09-07 holiday lands on Monday 2026-09-14. I implemented the stated algorithm, not the example.
2. **Named-nomination gate ordering.** §3.6 says the panel-supplement check runs "after the seat and conflict gates but before the eligibility machinery," which conflicts with §2.10's Order of Refusal. I followed §2.10: named-candidate checks (`ERR_PANELIST_INELIGIBLE` / `ERR_PANELIST_WINDOW_CONFLICT` / `ERR_PANELIST_CAPACITY_EXCEEDED`, band 11) -> `ERR_PANEL_SUPPLEMENT_UNPAID` (band 13) -> selector `ERR_NO_ELIGIBLE_PANELIST` (band 14).
3. **Scope of `ERR_NOT_OWNER` and `ERR_NOT_SEAT_HOLDER`.** The PRD narrative implies broad ownership enforcement; I scoped both from the SCAFFOLD `applies_to` lists — `ERR_NOT_OWNER` only on POST grounds / corrections / withdraw / court-challenges (plus the filing `complainant_id` mismatch), `ERR_NOT_SEAT_HOLDER` only on conflict-screening and votes.
4. **Identity checks vs. missing fields.** Band-3 identity comparisons (respondent email, seat claim) run only when the submitted value is actually a string, so an absent field still yields `ERR_INVALID_REQUEST` rather than an identity error.
5. **Clearing a panelist blackout.** "Supplying `unavailable_from` as null clears the declared blackout interval entirely" is implemented as clearing *both* endpoints, and an open-ended blackout (`unavailable_to` null) is treated as the single instant `unavailable_from`, with the interval closed on both ends so touching an endpoint collides.
6. **Publication digest.** `digest_text` is accepted in the body but always overwritten by the server-assembled `"<case_number> | <outcome> | rdnh=<bool>"`, since the PRD pins the stored format.
7. **`citable` / `precedent_weight` / `citation_count` are computed views**, recalculated per read from the current clock and live citation graph rather than stored snapshots, so a `SUSTAINED` challenge flips `superseded`/`citable` without a backfill pass.

## Step 7: Run tests and iterate — 2026-09-04T01:20:00.000Z

Subagent summary (verbatim):

Clean exit after 3 iterations.

## Summary

**Iterations run:** 3 (each a parallel 8-round sweep under `setsid nohup`).

Progression: 54/110 -> 106/110 -> **110/110**. Every failure encountered was deterministic (identical in all 8 rounds); no flakiness or load-induced failures appeared at any point.

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable; each failure was either a test-artifact bug or an implementation bug.

**Fixes applied to `test_suite/` and `test_helpers/`:**

- `test_suite/test_*.py` (17 files, 132 literals) — timestamp comparison literals lacked fractional digits (`"2026-08-01T00:00:00Z"`). PRD §2.5 states verbatim that `created_at` "is an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock", and §2.2 says the same of `api_request_timestamp`. Eight assertions compared `created_at`/`updated_at` directly against a bare-`Z` literal, contradicting that sentence outright; the rest applied the same non-PRD convention to other clock-stamped instants. Patched the 27 server-minted instant fields to `.000Z`. Deliberately left `unavailable_from`/`unavailable_to` (7 literals) bare — those are echoed caller input, not server-minted, and PRD states no normalisation for them.
- `test_helpers/fixtures.py`, `setup_single_member_panel` — `admit_panelist(..., roster_admitted_at=..., **panelist_overrides)` raised `TypeError: got multiple values` whenever a caller's `panelist_overrides` named `roster_admitted_at`. Replaced with a dict merge.
- `test_suite/test_17_layered_interactions.py` — added missing `nominate_seat` to the import list (`NameError` at line 381).
- `test_suite/test_06_boundary_instants.py`, `test_one_second_past_the_deadline...` — the request issued a court challenge as `Respondent` while omitting `respondent_email`, so the PRD-faithful server correctly refused it at the identity/schema bands (§2.10 bands 3 and 5) long before the temporal band the test targets. Added `respondent_email=VERIFIED_REGISTRANT_EMAIL` (matching what the sibling `file_court_challenge` helper already does) plus its import, so the request reaches the `ERR_CHALLENGE_WINDOW_CLOSED` check the test asserts.

**Fixes applied to `workspace/implementation/`:**

- `routes/panel.py`, `record_waiver` — moved the disqualifying-conflict check ahead of the appointment state gate. Screening always routes a score >= 60 to `CONFLICTED`, so consulting the state gate first made `ERR_CONFLICT_NOT_WAIVABLE` unreachable in the entire implementation despite PRD §3.6 and §2.10 band 9 both naming it. `ERR_INVALID_APPOINTMENT_STATE` remains reachable at this endpoint for a `NOMINATED`/`ACCEPTED` seat, which a separate test confirms.
- `routes/cases.py`, `cure_deficiency` — returned the case; now returns the cured notice. PRD §3.4 names the notice's transition as the operation's headline effect ("The notice becomes `CURED` with `cured_at` stamped from the clock"), and the notice is the resource the request targets via its required `notice_id`. The case's `DEFICIENT` -> `FILED` transition is unchanged.
- `routes/decisions.py`, `publish_decision` — the assembled digest rendered `rdnh_finding` via Python's `str(bool)`, emitting `rdnh=False`. PRD §3.9's prose is language-neutral, so the boolean renders in the API's own wire vocabulary: `rdnh=false`.

**Final per-round results — all 8 rounds 110/110 passed, 0 failed, 0 errors, 0 skipped** (~231s each). All eight `workspace/implementation/results.{1..8}.json` are present on disk and parse as complete JSON. Also verified the implementation keeps storage in-memory only — no SQLite, file writes, `/tmp` cache, or seeded rows.

Orchestrator verification (mandated by the known "claimed clean sweep with no artifacts" failure): independently parsed all eight `results.{1..8}.json` — every one reports passed 110 / failed 0 / total 110 / errors 0 / skipped 0, files 36 KB each, written 01:17-01:18. Independently counted 110 `def test_` functions still on disk (matching Step 5's 110, consistent with "0 deletions") and grepped `test_suite/` for `skip`/`xfail` — the single hit is the word "skips" inside a business-day docstring, no pytest markers. Step 8 will run, since Step 7 applied 3 `implementation/` fixes (skip condition not met).

## Step 8: Finalize PRD — 2026-09-04T01:32:00.000Z

Step 8 was NOT skipped: Step 7 applied 3 `implementation/` fixes plus test-artifact fixes, so the skip condition (zero iterations beyond baseline) did not hold. The Step 7 worklog entry was inlined verbatim as `<step_7_diff>`.

Subagent summary (verbatim):

Done. Verified `PRD_FINALIZED.md` is 437 lines and still ends with `| ERR_CHALLENGE_WINDOW_CLOSED | 409 |` at the close of the Error Code Catalogue.

## Line counts
- `PRD.md`: 435 lines -> `PRD_FINALIZED.md`: 437 lines (+2 lines, **+0.46%**). Six hunks changed; one new paragraph inserted, five sentences revised in place. No new sections.

## Changes
- **§2.5** — insert — new paragraph pinning that every server-stamped/derived instant (not just `created_at`/`updated_at`) renders as ISO 8601 UTC with three fractional digits, while a caller-supplied instant is echoed verbatim, and an omitted-but-defaulted instant is server-minted — `implementation/db.py:28-37` (`fmt`), all `db.fmt`/`db.now_str()` writes, vs. raw echoes at `routes/registry.py:81-82,169,205-210` and `routes/cases.py:514-526`.
- **§2.10 band 9** — revise — `ERR_CONFLICT_NOT_WAIVABLE` is the one exception to the ladder: at the waiver endpoint it is evaluated ahead of band 7's appointment-state gate; every other band-9 check stays behind band 7 — `implementation/routes/panel.py:183-187`.
- **§3.6 waiver paragraph** — revise — score-at-or-above-60 refusal is reported ahead of the seat's status (so a `CONFLICTED` seat reports the unwaivable conflict), with `ERR_INVALID_APPOINTMENT_STATE` still reachable for a `NOMINATED`/`ACCEPTED` seat — `implementation/routes/panel.py:183-187`.
- **§3.4 cure paragraph** — insert — the response reports the cured notice, not the case — `implementation/routes/cases.py:312-318`.
- **§3.9 digest** — revise — `rdnh_finding` renders as the lowercase wire boolean `true`/`false` — `implementation/routes/decisions.py:191-192`.
- **§2.1 Respondent bullet** — insert — `respondent_email` is a required field in the `Respondent` role, so omitting it (or sending a non-string) is `ERR_INVALID_REQUEST` at the schema band, not `ERR_RESPONDENT_IDENTITY_MISMATCH` — `implementation/routes/cases.py:545-547`, `implementation/routes/decisions.py:261-267`.
- **§3.8 challenge filing** — revise — same distinction, removing the reading that an omitted `respondent_email` yields the identity refusal — `implementation/routes/decisions.py:261-267`.

## Per-edit pre-edit search log

1. **Timestamp format.** (a) Subject: rendering of every persisted instant field. (b) Enumerated: `db.fmt`/`now_str`/`base_row`/`event_row`/`touch` in `db.py:28-147`; grepped every `db.fmt(`/`db.now_str()` callsite (34 sites across `routes/{cases,decisions,panel,registry}.py`, `services/logic.py`, `response.py:20`); grepped every `req_dt`/`opt_dt` callsite to find the complete set of caller-supplied instants (`registration_date`, `expiry_date`, `roster_admitted_at`, `unavailable_from`, `unavailable_to`, `deemed_received_at`, plus `current_utc`, which is not stored on any row). (c) Adjustment: added the third sentence covering `deemed_received_at`'s clock fallback (`routes/cases.py:522-526`), which is server-minted while the same field is verbatim when supplied — a two-way field my first draft would have mis-described.

2. **Band 9 ladder exception.** (a) Subject: relative order of band 9 vs band 7 across the whole ladder. (b) Enumerated all band-9 raise sites: `ERR_SEGREGATION_OF_DUTIES` (`routes/cases.py:332`, after the `FILED` state gate at :330), `ERR_REGISTRAR_SUSPENDED` (`routes/cases.py:418`, after the row-status gate at :415), `ERR_DOMAIN_LOCK_NOT_APPLIED` (`routes/cases.py:420`), `ERR_DOMAIN_NOT_LOCKED` at notification (`routes/cases.py:469`, after the state branch at :459-468) and at implementation (`routes/decisions.py:362`, after both state gates and before the band-12 deadline check), `ERR_CONFLICT_NOT_WAIVABLE` (`routes/panel.py:184`). (c) Adjustment: scoped the exception to the waiver endpoint and added the explicit "every other check in this band sits behind band 7" clause, so the note cannot be read as a general inversion.

3. **§3.6 waiver wording.** (a) Subject: refusal order and score/status coupling at `POST /appointments/{id}/waiver`. (b) Enumerated: `routes/panel.py:171-203` (full handler, incl. `_seat_the_neutral` at :123-129 running before the consent checks — consistent with band 11 before band 14), `calc.conflict_band` (`services/calc.py:144-149`) confirming score >= 60 => `CONFLICTED` and 30 <= score < 60 => `WAIVER_PENDING`, `_new_seat_row` (`routes/panel.py:20-42`) confirming `conflict_score` is `None` until screening, and `replace_seat` (:217-219) as the other consumer of appointment status. (c) Adjustment: wrote "a seat whose screening **already produced** a `conflict_score` at or above 60" and added the explicit `NOMINATED`-carries-no-score clause, so the unscreened seat's `ERR_INVALID_APPOINTMENT_STATE` path is not mis-described by the impl's `score is not None` guard.

4. **Cure response resource.** (a) Subject: which resource the corrections endpoint returns. (b) Enumerated: `routes/cases.py:294-318` (returns `db.public(notice)`, HTTP 200 via `response.ok`), compared against the sibling state-advancing handlers to confirm no parallel endpoint is implicated — `clear_compliance` returns the case (:363), `rerequest_verification` returns the verification row (:390), `answer_verification` returns the row (:442), `record_delivery` returns the attempt (:536), `replace_seat` returns the predecessor (:246), `resolve_challenge` returns the challenge (:329,345); also checked §4's table row for `/corrections` and §2.2's "returns the created or updated resource". (c) Adjustment: scoped the new sentence to this operation only and phrased it as "the row the request named through `notice_id`", leaving §4's table description (which speaks to the state transition) untouched.

5. **Digest boolean.** (a) Subject: server-assembled `digest_text`. (b) Enumerated: the only assembly site `routes/decisions.py:188-198`; grepped the whole impl for any other boolean-to-text rendering or `str(` on a stored value (only `db.py:67` `str(uuid4())` and `validate.py:194-196` query-string parsing — neither persists text). Also checked the void-before-issue path (`routes/panel.py:233-238` sets `VOIDED` with `outcome` still `None`), which is reachable at publication. (c) Adjustment: confined the new clause strictly to the `rdnh=` term and left PRD's existing wording for the `outcome` part verbatim, so the `outcome is None` publication path is not newly (mis)described.

6/7. **`respondent_email` band.** (a) Subject: how an absent vs wrong `respondent_email` is refused, in every role and endpoint that reads it. (b) Enumerated both and only both readers: `routes/cases.py:545-547` (`POST /cases/{id}/responses`, identity checked only when a string is present, then `req_str` -> `ERR_INVALID_REQUEST`) and `routes/decisions.py:261-267` (`POST /decisions/{id}/court-challenges`, identity checked only for role `Respondent` with a string present, `req_str` required only when role is `Respondent`); plus `logic.ensure_respondent_identity` (`services/logic.py:91-93`) and `logic.ensure_case_owner` (:81-83) for the `Complainant`-role branch of the same challenge endpoint. (c) Adjustment: scoped the §2.1 sentence to "any payload submitted in the `Respondent` role" rather than "any payload containing the field", because a `Complainant` filing a challenge is neither required to supply it nor identity-checked on it; and in §3.8 I reworded rather than deleted, keeping the `ERR_RESPONDENT_IDENTITY_MISMATCH` attachment to a non-matching address.

Orchestrator verification: `PRD_FINALIZED.md` is 437 lines vs `PRD.md` 435, and `diff` reports 14 changed lines — i.e. a real minimal patch, not a byte-identical copy. Tail still closes on the final Error Code Catalogue row.

## Step 9: Complete PRD — 2026-09-04T02:05:00.000Z (pass A + pass B)

Orchestrator decision, recorded for the record: Step 9 was deliberately split into THREE SEQUENTIAL file-partitioned passes over disjoint slices of `implementation/`, all editing the same `workspace/PRD_COMPLETED.md` in place. Rationale — a single-agent full-implementation scan of a 2805-line implementation against a 437-line PRD routinely degenerates into a byte-identical copy of the source PRD (the scan never actually runs). Partitioning by file forces each agent to walk a slice it can hold in context. Passes must be sequential, not concurrent, because they share one edit target. Slices: A = app.py, db.py, response.py, middleware.py, errors.py, validate.py, routes/registry.py; B = routes/cases.py, services/logic.py; C = routes/panel.py, routes/decisions.py, services/calc.py. Union of the three slices = every .py file in `implementation/`.

### Pass A summary (verbatim):

Pass A complete.

**File deltas**
- `PRD_FINALIZED.md`: 437 lines / 96,564 chars
- `PRD_COMPLETED.md`: 439 lines / 102,078 chars (+2 lines, +5,514 chars)
- Final-line check: **passed** — file still ends with `| `ERR_CHALLENGE_WINDOW_CLOSED` | 409 |`

**Counts**: 18 ambiguity-pins, 1 mismatch-revision (19 Edit calls, all in-paragraph; no new sections, no table rows added).

**Changes**
- §2.1 Actors/Auth — insert — ambiguity — both header values are trimmed before examination and an empty-after-trim value counts as absent (`ERR_UNAUTHENTICATED`) — `middleware.py:24-31`
- §2.2 Success envelope — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from `A`-`Z`/`0`-`9` — `response.py:10,14`
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — `response.py:20`
- §2.3 Pagination — insert — ambiguity — empty-string `limit`/`offset` treated as omitted; out-of-range refused not clamped; creation-timestamp ties broken by insertion sequence (never by `id`); filters applied before the offset window; no-match filter yields an empty page not a 404; boolean query filters accept `true/false/1/0` case-insensitively after trimming, anything else `ERR_INVALID_REQUEST` — `validate.py:155-198`, `db.py:157-161`, `response.py:36-64`, `routes/registry.py:112-126`
- §2.4 Logical clock — insert — ambiguity — the clock may be moved backwards (no monotonicity) and the call reports an empty `data` object — `routes/registry.py:216-222`
- §2.4 Deadline sweep — insert — ambiguity — stage 1 closes the case only when it is still `DEFICIENT` and `closed_case_count` counts only those closes; each stage visits candidates in creation order; every due-instant comparison is strict; the sweep ignores any request body — `routes/registry.py:225-276`
- §2.5 Common properties — insert — ambiguity — caller-supplied instants are re-read as ISO 8601 and converted to UTC for comparison, a zone-less value is read as UTC, unparseable values fail at the schema band — `db.py:40-50`, `validate.py:103-108`
- §2.6 Path resolution — insert — ambiguity — registrar and complainant path ids have no dedicated code and report `ERR_RESOURCE_NOT_FOUND` — `routes/registry.py:46,53,148` via `services/logic.py:59-64` (read for wording only)
- §2.6 Body-referenced ids — **revise** — **mismatch** — the enumerated list omitted `registrar_id`, which impl does resolve in the domain-creation body; also pinned that a non-string reference draws the same 404 and that an omitted/null reference falls to the schema band — `routes/registry.py:66-68`
- §2.10 band 5 (Schema) — insert — ambiguity — absent/unparseable/non-object body read as an empty object (missing-field error, never a parse error); explicit `null` counts as absent; no type coercion (int rejects strings/floats/bools, bool rejects `"true"`/`"false"`, strings measured untrimmed) — `middleware.py:37-42`, `validate.py:17-84`
- §3.1 Registrars — insert — ambiguity — `name` 1-255, `contact_email` 1-320 and not shape-checked; duplicate `iana_id` refused with `ERR_INVALID_REQUEST` after the schema band — `routes/registry.py:23-29`
- §3.1 Domains — insert — ambiguity — `registrant_name_public` 1-255, `registrant_email_public` 1-320; no ordering relation enforced between `registration_date` and `expiry_date` — `routes/registry.py:70-73`
- §3.1 Out-of-band lock — insert — ambiguity — no registrar-of-record comparison at this surface (any `RegistrarAgent` may lock any domain; `ERR_REGISTRAR_MISMATCH` unreachable here); re-applying `LOCKED` re-stamps `locked_at` — `routes/registry.py:98-109`
- §3.1 Complainants — insert — ambiguity — `legal_name` 1-255, `email` 1-320 — `routes/registry.py:135-137`
- §3.1 Complainants — insert — ambiguity — the complainant read makes no ownership comparison — `routes/registry.py:145-149`
- §3.1 Roster admission — insert — ambiguity — `full_name` 1-255; `roster_admitted_at` required ISO 8601; `firm_name` up to 255 defaulting to null; `specializations` defaults to `[]`, may be empty, may repeat tags, may not contain a blank entry — `routes/registry.py:157-162`
- §3.1 Availability — insert — ambiguity — neither reading nor revising a panelist compares `X-User-ID` to the path id; `unavailable_from: null` clears both ends regardless of any `unavailable_to`; `unavailable_to: null` alone clears only that end; the call always touches the row (`updated_at`/`version`) even when it carries nothing — `routes/registry.py:186-212`
- §4 preamble — insert — ambiguity — trailing slash not significant; unmatched path *and* disallowed method both answer `ERR_RESOURCE_NOT_FOUND` / HTTP 404, never 405 — `app.py:18,35-39`

**Verified with no change needed**: all 47 error-id->HTTP-status pairs in `errors.py:12-63` match the §5 catalogue exactly; §4's authorised-role lists match every `auth(...)` call in `routes/registry.py`; 201-on-create / 200-on-modify holds throughout the slice; `db.py` epoch, ISO-8601 3-fraction-digit rendering, un-prefixed UUIDs, `D-2026-%06d` docket minting, `base_row` vs `event_row` field sets and `touch` semantics are already uniquely pinned in §2.4/§2.5.

**Not pinned deliberately**: `app.py:45-47`'s `ERR_INTERNAL` safety net (not in the catalogue, and adding a row would have disturbed the required final line) and `app.py:20` key-order preservation (not semantically observable).

### Pass B summary (verbatim):

Pass B complete.

## Result

`workspace/PRD_COMPLETED.md`: **439 lines / 102,078 chars -> 439 lines / 108,558 chars** (28 in-paragraph edits; no new lines, sections, or paragraphs). Final-line check **passed** — file still ends with `| `ERR_CHALLENGE_WINDOW_CLOSED` | 409 |`. Endpoint table intact (54 rows).

**Counts: 22 ambiguity-pins, 6 mismatch-revisions.**

### Changes

- §2.10 band 3 — revise — mismatch — identity/ownership comparisons are made against a row the path names, so path identifiers resolve *first* (nonexistent case => `ERR_CASE_NOT_FOUND`, not `ERR_NOT_OWNER`); band 3 then precedes nested/body-referenced existence — cases.py:142-143, 160-161, 297-298, 405-406 (verified identical in decisions.py:256-260, 351-354, panel.py)
- §3.2 filing — revise — ambiguity — `complainant_id` ownership comparison bites only on a string actually supplied; omitted/null/non-string fall to schema/existence — cases.py:48-50
- §3.2 filing — insert — ambiguity — initial row values: three paid totals 0, `deficiency_round_count` 0, `default_recorded` false, `deadline_variant_applied` already `PROVISIONAL`, nine fields null — cases.py:85-104
- §3.2 pricing — insert — ambiguity — a complainant-elected `THREE` case is never re-priced; only the respondent's election re-runs the assessment — cases.py:106 vs 575 (`reprice` has no other call site)
- §3.2 grounds — revise — ambiguity — trademark trio stored as null on other elements, `mark_registration_number` 1-128, `cited_decision_ids` uncapped/no-blank/duplicates allowed, no state gate, case `version` untouched — cases.py:170-198
- §3.2 grounds — insert — ambiguity — non-array `cited_decision_ids` => `ERR_INVALID_REQUEST`; non-string member => `ERR_RESOURCE_NOT_FOUND` — cases.py:163-166, 170
- §3.3 ledger — insert — ambiguity — `reference` <=255; zero-amount and PROVIDER-non-write-off refused at schema band, zero tested first; no state gate — cases.py:220-225
- §3.3 withdrawal — revise — ambiguity — `reason` <=2000 — cases.py:145
- §3.3 withdrawal cascade — revise — mismatch — only `REQUESTED` verifications flip; registrar counter +1 but row `escalation_count` untouched; an already-`OVERDUE` row is left entirely alone; expired notice keeps `cured_at` null — cases.py:24-40
- §3.4 cure — revise — ambiguity — a notice belonging to another case is `ERR_INVALID_CASE_STATE`, not `ERR_RESOURCE_NOT_FOUND` — cases.py:307-308
- §3.4 cure — revise — ambiguity — `correction_notes` >=1 char, unbounded above — cases.py:303
- §3.4 clearance — revise — ambiguity — `reviewer_notes` <=4000 — cases.py:326
- §3.4 clearance — insert — ambiguity — `mutual_jurisdiction` shape is a schema-band `ERR_INVALID_REQUEST` tested ahead of the state gate — cases.py:327-331
- §3.4 verification row — insert — ambiguity — created with `lock_applied` false and four null fields — cases.py:347-358
- §3.4 re-request — insert — ambiguity — body ignored; reactivates the most recently created `OVERDUE` row; no-`OVERDUE` case => `ERR_INVALID_CASE_STATE`; case status tested first — cases.py:375-381
- §3.4 answer — revise — ambiguity — name 1-255, email 1-320, remarks <=2000 — cases.py:412-414
- §3.4 answer — revise — mismatch — the row's status is the only state gate (case status never examined, so an `OVERDUE` row left by a withdrawal still drives its closed case to `NOTIFICATION_PENDING`); response reports the verification row — cases.py:415, 440-442
- §3.5 dispatch — revise — ambiguity — `address` 1-512 — cases.py:456
- §3.5 delivery — revise — ambiguity — non-`SENT` => `ERR_INVALID_CASE_STATE`, case status unexamined; counterpart optional field validated then discarded; `dispatched_at` check precedes the `SENT` gate — cases.py:514-535
- §3.5 delivery — revise — ambiguity — `failure_reason` optional, <=2000, null when omitted — cases.py:515, 534
- §3.5 re-dispatch — insert — mismatch — no lock check on re-dispatch; recomputation overwrites `provisional_response_due_at` and resets `deadline_variant_applied` to `PROVISIONAL` — cases.py:469, 491 + logic.py:331-336
- §3.5 response — revise — ambiguity — `respondent_email` 1-320 — cases.py:547
- §3.5 response — insert — ambiguity — `nominated_panelist_ids` entries never resolved against the roster; duplicates allowed — cases.py:550-551
- §3.6 selection — revise — ambiguity — insertion order settles a residual tie after the three documented keys — logic.py:313-316
- §3.6 blackout — insert — ambiguity — null `unavailable_from` => no blackout at all; set-from with null-to => single-instant blackout — logic.py:287-293
- §3.6 honoraria — insert — ambiguity — a seat already holding the computed amount is not re-stamped — logic.py:216-220
- §3.9 precedent — revise — mismatch — `citation_count` counts citation *occurrences*, so a repeated identifier inside one ground's array contributes twice — logic.py:366-372
- §4 endpoint table — revise — mismatch — `GET /udrp/cases` also filters on `status`, validated against the fifteen case statuses with `ERR_INVALID_REQUEST` otherwise — cases.py:127

No edits were made to passages pass A had already patched (envelope, pagination, schema band, clock/sweep, §2.5/2.6 conventions, §3.1); §2.10 band 3 was untouched by pass A and is the one shared passage I revised.

### Pass C summary (verbatim):

Pass C complete.

## Result

**PRD_COMPLETED.md**: 439 lines / 108,558 chars -> **439 lines / 114,970 chars** (+6,412 chars). Line count unchanged because every edit was an in-paragraph insert or revision — no new paragraphs, no new sections.

**Counts**: 13 ambiguity-pins, 6 mismatch-revisions (19 Edit calls total).

### Changes

- §2.7 — insert — ambiguity — `expected_case_version` must be a non-negative integer; a negative or non-integer value fails the schema band ahead of the version comparison — `validate.py:53` via `panel.py:66`, `decisions.py:34`
- §3.6 (nomination fee gate) — revise — **mismatch** — PRD said the fee gate sits "before the eligibility machinery"; impl checks it *after* a named candidate's own eligibility refusals and *before* the provider's selector, matching §2.10's bands 11/13/14 — `panel.py:76-80`
- §3.6 (new seat row) — insert — ambiguity — pinned all initial appointment field values, and that the `status`/`seat` list filters are enum-validated (`ERR_INVALID_REQUEST`) — `panel.py:20-42`, `panel.py:96-106`
- §3.6 (screening gate) — insert — ambiguity — the seat's status is the only state gate; the case's status is never examined — `panel.py:144`
- §3.6 (direct seating) — insert — ambiguity — when the re-run window/capacity check fails, the **whole screening is refused and nothing is persisted** (disclosures, score, `screened_at` all stay unset, seat stays `NOMINATED`) — `panel.py:151-152`
- §3.6 (waiver) — insert — ambiguity — `waiver_respondent` records false when omitted on a defaulted case; the band-11 window/capacity checks are reported in preference to `ERR_WAIVER_INCOMPLETE`; case status not examined — `panel.py:188-198`
- §3.6 (honoraria) — revise — **mismatch** — the PRD example claimed a 297500 pool gives the presiding seat "500 cents more than a flat 40 percent share"; 40% of 297500 is exactly 119000, and that pool is unreachable. Replaced with the reachable expedited three-member pool 293125 -> 87937/87937/117251 (verified against `calc.honoraria_allocation`) — `calc.py:92-103`
- §3.6 (replacement) — revise+insert — **mismatch** + ambiguity — predecessor state gate (`ERR_INVALID_APPOINTMENT_STATE`); no case-status gate and no version pin, yet the case's `version` always advances; successor's `nominated_by` is always `PROVIDER` while `selected_by_provider` tracks whether a name was given; the predecessor's own row is excluded from the successor's eligibility tests so the same neutral can be re-seated; `reason` (<=2000) is validated then **discarded**, not "recorded" — `panel.py:206-246`
- §3.7 (drafting) — insert — ambiguity — the drafting-seat requirement is refused as **`ERR_INVALID_REQUEST` at the schema band**, ahead of both the case-status gate and the version pin — `decisions.py:38-47`
- §3.7 (ballots) — insert — ambiguity — the seat comparison bites only on a string `seat` (otherwise schema band); the decision must be in `DRAFT` (`ERR_INVALID_DECISION_STATE`) and the case's status is never examined — `decisions.py:95-108`
- §3.7 (issuance) — insert — ambiguity — any body, including none, is accepted and ignored — `decisions.py:140`
- §3.8 (business-day example) — revise — **mismatch** — PRD said a decision issued Fri 2026-08-28 falls due Fri 2026-09-11 / "fourteen calendar days"; `calc.implementation_deadline` actually yields **Mon 2026-09-14**, three weekends plus the holiday, seventeen calendar days (verified by running the function) — `calc.py:217-226`
- §3.8 (challenge filing) — revise+insert — ambiguity — `jurisdiction` exactly two *uppercase* letters, `docket_number` 1-128, `respondent_email` 1-320; `filed_by` recorded as supplied and never cross-checked against the acting role; the case's status is never a gate and the move to `STAYED` is conditional on `IMPLEMENTATION_WAITING` while `version` advances either way; the challenge list makes no ownership comparison — `decisions.py:254-299`
- §3.8 (challenge resolution) — insert — ambiguity — `resolution_note` up to 4000 chars, null when omitted; the response reports the resolved challenge row, never the decision or case — `decisions.py:311, 329, 345`
- §3.8 (execution gates) — revise — **mismatch** — PRD listed the clock check before the lock check; impl checks `ERR_DOMAIN_NOT_LOCKED` (band 9) ahead of `ERR_IMPLEMENTATION_PERIOD_ACTIVE` (band 12). Also `registrar_action_reference` (<=255) is validated then **discarded**, not "recorded" — `decisions.py:356-366`
- §3.8 (execution effects) — insert — ambiguity — `locked_at` left standing on an executed outcome vs nulled on release; the closing cascade does not touch the lock again; no refund; the response reports the decision — `decisions.py:368-383`
- §3.9 (publication input) — insert — ambiguity — `precedent_tags` entries may repeat, may not be blank, and any upper-case character is `ERR_INVALID_REQUEST`; `digest_text` up to 4000 chars, validated then discarded — `decisions.py:178-182`
- §3.9 (publication output) — insert — ambiguity — a draft voided before issuance is still publishable and its null `outcome` renders in the digest as the literal `None`; the response is the **201 precedent entry in its on-read form**, not the decision — `decisions.py:191, 207`
- §4 endpoint table — revise — **mismatch** — `GET /udrp/appointments` row listed only `case_id`/`panelist_id`; impl also filters on `status` and `seat` (already pinned in §3.6) — `panel.py:96-106`

### Integrity checks

- Final line is still `` | `ERR_CHALLENGE_WINDOW_CLOSED` | 409 | `` — not mid-sentence.
- §4 table intact: 55 table lines (header + separator + 53 endpoint rows), unchanged count.
- §5 catalogue intact: 50 `ERR_*` rows.
- All 26 section/subsection headers present in order (§1 through §5).

One note for the caller: I verified both arithmetic mismatches (the honoraria remainder example and the ten-business-day date) by executing `calc.py` directly rather than by inspection, so the replacement figures are the implementation's own output.

### Step 9 aggregate + orchestrator verification

Across the three passes: **53 ambiguity-pins and 13 mismatch-revisions**, 66 edits total, spanning every `.py` file in `implementation/`.

Independent orchestrator checks on the final artifact:
- `PRD.md` 435 lines / 94,362 chars -> `PRD_FINALIZED.md` 437 / 96,564 -> `PRD_COMPLETED.md` 439 / 114,970 (+21.9% chars over the source PRD, all of it in-paragraph pinning).
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md`; `diff` reports 118 changed lines — the scan genuinely ran (this was the specific failure mode the three-pass split was designed to prevent).
- Structural integrity re-verified independently: 24 markdown headings, §4 holds 53 method-prefixed endpoint rows, §5 holds 50 `ERR_*` rows, 50 distinct error ids document-wide, file ends on the final catalogue row.
- Final 8-round sweep artifacts still on disk and green: 8 files, all (110, 110).

Pipeline complete through Step 9.
