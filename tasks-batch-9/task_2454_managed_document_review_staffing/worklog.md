# Worklog — task_2454_managed_document_review_staffing

## Step 1: Create task directory — 2026-09-02T20:02:17.578Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2454_managed_document_review_staffing` and its `workspace/` subdirectory. Index 2454 was pre-assigned by the caller; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-02T21:23:38.670Z

All three artifacts are generated and the lint is clean. Verdict block, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2454_managed_document_review_staffing/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2454_managed_document_review_staffing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2454_managed_document_review_staffing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     13
  §1.8 instances scanned:     21
  §1.9 instances scanned:     52
  Calls scanned (§1.8+§1.9):  1215

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2454_managed_document_review_staffing/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`. Written purely from the scenario text plus the skill spec — no sibling task was read.

**SCAFFOLD.yaml (§1.0–§1.7):** 13 entities (Client, Matter, ReviewProtocol, Reviewer, ConflictsScreening, ConfidentialityAgreement, SecureEnvironmentSession, Batch, Assignment, QCSample, PrivilegeLogEntry, plus ledger-style `ScorecardEvent` and `BudgetLedgerEntry` with `common_fields: false`); 10 state machines; 3 OCC concurrency rules; 10 calculations; 43 ordered validations; **57 endpoints**; 52 errors; 5 roles (EngagementManager, StaffingCoordinator, QCLead, Reviewer→entity_backed Reviewer, ClientCounsel→entity_backed Client). Profile: compliance_audit / quota_allocation, graph topology, parallel state shape, segregation_of_duties, immediate consistency.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8):** all **9 rule_ids, 21 instances** (2/3/2/2/3/3/2/2/2), every pinned figure pre-computed with Decimal ROUND_HALF_UP (rate 213 → 85200; second-level 128; invoice waterfall 98832→1977→100809→3024→97785; projections 71050 vs 85200, variance −14150; accuracy 0.9833 vs 0.9875; hourly 109→114 min→12350).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9):** **78 instances across all 9 guide sections** — 52 with full `test_recipe`s and 26 `excluded_because` stubs that each cite an existing §1.8 instance. Per section: entities 12, state_machines 13, calculations 11, validations 8, endpoints 4, errors 16, rbac 5, cross-cutting 7, consistency 2. Every error in the 52-entry catalog is either triggered by a corner recipe or delegated to a named §1.8 instance.

## Design adjudications made

- **`Assignment.billable_minutes` added to §1.1** — the hourly 6-minute-increment instance asserted a field that did not exist; added as a computed field (0 under PER_DOCUMENT).
- **Dangling calc ref fixed** — the Reviewer `ENGAGED→REMOVED` trigger pointed at a non-existent `calculations.reviewer_removal_evaluation`; repointed to `reviewer_scorecard_strikes`.
- **`grounds:` ref forms** — bare `endpoints` and `roles[...]` are not resolvable ref forms; replaced with concrete `endpoints[METHOD /path]` refs.
- **Close-gate adjudication** — `ERR_MATTER_NOT_CLOSEABLE` is unreachable with a single fully-batched batch (the QC_CLOSEOUT cascade satisfies all three clauses at once), so it needed a 599/600-document split, which also let the corner walk cover the `QC_CLOSEOUT → IN_REVIEW` revert edge.
- **Release always needs privilege entries** — the quota floor `max(2, ceil(n*0.20))` means any release path must log and validate ≥2 PrivilegeLogEntry rows; the bubble-up recipes were rebuilt around that, and a separate instance asserts the floor firing at 0 entries.
- **Priority-collision avoidance in negative recipes** — capacity saturation (not credential lapse) is used for the empty auto-assign pool so priority 16 cannot mask 36; the min-staffing error needed its own `min_staffed_reviewers: 2` matter; `ERR_SECOND_LEVEL_SAME_REVIEWER` (20) is asserted as outranking `ERR_TIER_MISMATCH` (35) on the same request.
- **Lint-driven fixes** — the system-field-injection instance was renamed to `system_and_computed_fields_input_ignored` so the intentional unknown keys are read as a negative test, and two list-endpoint captures were rewritten to `$.data[0].…` (quoted, since PyYAML rejects an unquoted `[` in flow mappings).

## Step 3: Copy shared files — 2026-09-02T21:23:38.670Z

Copied `./INSTRUCTION.md` → `tasks/task_2454_managed_document_review_staffing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T21:42:31.000Z

The PRD is complete and verified.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2454_managed_document_review_staffing/workspace/PRD.md` — **515 lines, 117,478 bytes**. Last section heading: **`## 5. Error Code Catalogue`**; the file's final line is the complete table row `` | `ERR_BUDGET_WOULD_EXCEED` | 402 | `` followed by a newline, so it terminates at a real section boundary with no mid-sentence truncation and no audit footer.

## Structure produced
- `## 1. Introduction` (3 paragraphs)
- `## 2.` §2.1 RBAC (five roles, `X-User-ID`/`X-User-Role`, all five identity bindings) · §2.2 pasted byte-for-byte from `section-2.2-response-structure.md` · §2.3 Pagination · §2.4 Logical Clock · §2.5 the full 43-rank validation precedence chain · §2.6 common properties & version semantics · §2.7 stale-version guards · §2.8 money/rounding · §2.9 closed-coverage vs half-open-occupancy · §2.10 cascade discipline · §2.11 ledger & scorecard streams
- `## 3.` nine subsections (3.1 matter intake → 3.9 closeout/closure/commercial readout), carrying the assignment gate, the pinned rate/commitment order, the auto-assign eligibility filter + weighted score + tie-break chain, the pinned billing order, the QC inclusive-boundary threshold, the depth-4 QC-failure cascade, the privilege-validation quota, and the four-step invoice waterfall
- `## 4.` intro paragraph + **4-column** table, 57 endpoint rows
- `## 5.` intro paragraph + **2-column** table, 52 error rows

## Hard contracts — all PASS
- **Contract 1 (Field-Name Coverage): PASS.** All 118 `entities[].fields[].name` values present in backticks; all 97 distinct `input`/`output`/query/path identifiers present (including `to_iso8601`, `current_utc`, `expected_matter_version`, `expected_batch_version`, the 10 scorecard-read fields and the 13 spend-projection fields); `id`, `created_at`, `updated_at`, `version`, `limit`, `offset` all present.
- **Contract 2 (Rule Coverage): PASS.** All 52 error IDs present; all 57 endpoints present as `| METHOD | \`path\` |` rows; all 67 enum values and every state name from all 10 state machines present; all 3 concurrency rules, all 9 calculation rules with their constants (tier multipliers 1.00/1.15/1.35, language premium, pass multiplier 0.60, 6-minute increment, sample floor 10, quota floor 2, removal threshold 3, surcharge factor, discount bands 100000/249999/250000, accuracy floor 0.9000 with 50-document minimum, pace cap 1.5), both dual-variant selections, and the sibling-branch asymmetry of the `second_level_required` fork. No symbolic operators, no code fences outside §2.2, no fuzzy quantifiers.
- **Contract 3 (§3 Path Purity): PASS.** Zero backtick tokens in §3 begin with `/`, name a bare HTTP method, or combine method and path — §3 refers to operations only by capability phrase. §1–§2 are likewise path-free.

## Notes
- The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced; no worked-example numbers from the scaffold's `worked_example` blocks were copied into the prose.
- Two scaffold ambiguities resolved and recorded in prose: (a) `REMOTE_VDI` gating — validation rank 22 names two flags while the `workstation_class` field description says three, so §3.5 states all three (`remote_work_permitted`, `remote_work_authorized`, `remote_work_addendum`) under `ERR_REMOTE_WORK_NOT_AUTHORIZED`; (b) `privilege_basis` membership in the approved protocol's `privilege_criteria` and `document_ref` uniqueness within a batch have no dedicated error, so both are attributed to `ERR_INVALID_REQUEST`.
- Fixed one typo in §3.1 ("alongthe" → "along with the") and corrected §2.7's opening count to "three write operations … under two distinct guards".

**Orchestrator truncation check (per caller instruction):** independently verified — `grep -c '^| \`ERR_'` = 52, endpoint rows = 57, final heading `## 5. Error Code Catalogue` at line 458, tail ends on a complete table row. PRD is NOT truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T00:39:00.000Z

Test infrastructure and suite are complete.

## Files written

`test_helpers/` (Stage 1, 9 modules): `__init__.py`, `api_client.py` (typed wrapper over every endpoint), `api_errors.py` (error-id constants), `assertions.py` (money/rate/pace/status/scorecard helpers plus pure re-implementations of the contract-rate, pinned-rate, selector-score and sample-target formulas), `constants.py`, `factories.py` (payload builders), `fixtures.py` (`ReviewLadder` driver + 30 function-scoped state fixtures), `test_users.py` (role headers, `raw_headers`), `types.py`.

`test_suite/` (Stage 2): `conftest.py` + 18 test files, **94 tests**:
test_01 (4), test_02 (6), test_03 (4), test_04 (4), test_05 (6), test_06 (6), test_07 (4), test_08 (4), test_09 (4), test_10 (13), test_11 (9), test_12 (6), test_13 (4), test_14 (3), test_15 (8), test_16 (4), test_17 (4), test_18 (1).

## Per-queue coverage

- **Queue A (Difficulty, §1.8)** — 21/21 instances, 0 stubs, 42 tests (>=2 per instance), zero skips.
- **Queue B (Corner, §1.9)** — 50/52 FULL instances, 52 tests (>=1 per instance). The 26 stub instances carrying `excluded_because` were not translated, as specified.

## Instances skipped (2, both queue B)

- `Corner/state_machines/close_refused_while_documents_remain_unbatched` — premise contradicted by the PRD: with one stranded unbatched document the matter never reaches `QC_CLOSEOUT`, so a close attempt is answered by the rank-12 `ERR_INVALID_STATE`, not the asserted `ERR_MATTER_NOT_CLOSEABLE`.
- `Corner/errors/conflicts_and_agreement_gates_fire_separately` — setup unconstructible: agreement issuance requires an already-`CLEARED` screening for the pair, so "EXECUTED agreement with no screening at all" is unreachable.

## Design/PRD conflicts resolved in the PRD's favour

`ERR_SESSION_OUTSIDE_COVERAGE` asserted at 422 (design said 409); a `PENDING` sample's `discrepancy_rate` asserted as `0.0000` (design said null); the version-walk instance uses relative rather than absolute matter versions where the PRD does not uniquely derive the absolute figure. Response envelope asserted through the framework validators (`{response_type, data, meta}`), not the design yaml's inaccurate `{success, data, error_id, message}`.

## Audits run (all clean)

- **C4**: exactly one `Design:` line, last line of every one of the 94 docstrings; all 71 distinct tags resolve to real non-stub instances; no untagged, dual-tagged or stub-tagged tests.
- **C1/C2/C3**: every docstring now opens with a `PRD §X.Y: "…"` citation. This was missing suite-wide and I added it to all 94 tests, then machine-verified each quote is a whitespace-normalised literal substring of `PRD.md`, is a full rule-bearing sentence (error id / threshold / transition / side effect / field), and is not an endpoint title or heading.
- Scaffold-leakage: 0 occurrences of "scaffold" or design-index references in any generated text.
- Import hygiene (no unused imports outside the intentional `conftest` re-export block), byte-compile clean, `pytest --collect-only` collects all 94.

Nothing under `workspace/implementation/` was read or written.

## Step 6: Generate implementation — 2026-09-03T00:39:00.000Z

Implementation complete and verified.

## Files written (23 files, ~3,870 lines)
All under `/home/ubuntu/github/CodingPRD/tasks/task_2454_managed_document_review_staffing/workspace/implementation/`:

- `start.sh` (guarded `pip install` only if Flask is missing, then `exec python3 app.py`; honours `PORT`, default 10000), `requirements.txt`
- `app.py` — factory, per-request `RLock`, global handlers for `ApiError` / `HTTPException` (404, 405, 400/415 → `ERR_INVALID_REQUEST` 422) / bare `Exception`
- `db.py` — in-memory `Store` with 13 dicts, logical clock pinned at `2026-08-01T00:00:00.000Z`, `fmt_ts` (exactly 3 fractional digits), monotonic `_seq` for ordering tie-breaks
- `errors.py` (all 53 catalogue ids + 3 transport ids), `response.py` (envelope, pagination), `middleware.py` (ranks 1-3), `validation.py` (rank-8 primitives)
- `services/compute.py` (all constants, lookups, derived figures, money, interval predicates, 13 serializers), `services/cascade.py` (ledger/scorecard append, staffing sync, lazy expiry, voiding, removal, blocked-screening cascade)
- `routes/`: `clock`, `clients`, `matters`, `protocols`, `reviewers`, `screenings`, `agreements`, `sessions`, `batches`, `assignments`, `qc`, `privilege`

**57 endpoints**, exactly matching the PRD's 57-row endpoint table (`app.url_map` rule count verified). Storage is dicts only — a grep for `sqlite`/`open(`/`json.dump`/`pickle`/`/tmp`/`shelve` returns nothing; no entity is seeded, every row comes from a client call.

## Verification
Booted from a cold process via `bash start.sh` and ran three throwaway smoke suites: PER_DOCUMENT happy path; error-rank/HOURLY/second-level/QC-failure/rework/privilege-challenge-amend/release/closeout/close/spend-projection; and cascade coverage (budget ceiling with zero ledger writes, 3-strike removal with `REMOVAL` event and matter fall-back to `STAFFING`, blocked re-screening depth-4 cascade producing `REVOKED`/`REVOKED`/`VOIDED`/`SOURCED`/batch `CREATED` plus `COMMITMENT`+`REVERSAL` netting to 0, lazy expiry bumping agreement `version` inside a read, suspension revoking sessions, `required_pace_dph` → null past the deadline). Representative verified values: effective rate 115 (100 × 1.15 rounded before multiplication), commitment 460, HOURLY 61 min → 66 billable min → 6600 cents, discrepancy 0.2 → FAILED with `['QC_FAILURE','PRIVILEGE_MISS']`, invoice waterfall 9600 → 960 surcharge → 10560, headroom 490400.

## PRD ambiguities resolved
1. **Auth header** — PRD says `X-User-Role`, SCAFFOLD says `X-Role`; accept `X-User-Role` first, fall back to `X-Role`.
2. **REMOTE_VDI gating** — rank 22 names two flags, §3.5 says "three independent authorisations"; enforced three (matter `remote_work_permitted`, reviewer `remote_work_authorized`, governing agreement `remote_work_addendum`).
3. **Blocked-screening cascade scope** — links 3/4 run only when an `EXECUTED` agreement was revoked ("the PENDING arm does nothing further").
4. **Lazy expiry trigger points** — agreement read/list, matter read, and every validation that consults coverage (agreement overlap, session schedule/activate, assignment create/start/progress/submit, auto-assign pool).
5. **Reviewer `pace_dph`** — pooled `sum(documents_coded)/(sum(minutes_logged)/60)` over SUBMITTED+COMPLETED, 2 dp, 0.00 when no minutes.
6. **HOURLY matter `remaining_work_basis_cents`** — contract rate treated as 0 since `per_document_rate_cents` is null.
7. **`qc_sample_target_size` with no APPROVED protocol** — most recently approved protocol, else the pct frozen at carve time.
8. **Unspecified-error choices** — session activation outside its own window and adverse-party-equals-client → `ERR_INVALID_STATE`; session coverage failure → `ERR_CONFIDENTIALITY_NOT_EXECUTED`.
9. **Conditional required fields** (`change_notes`, `challenge_note`, duplicate `document_ref`, `privilege_basis` outside protocol criteria) → `ERR_INVALID_REQUEST` at rank 8.
10. **Dissolve** returns `ERR_BATCH_NOT_DISSOLVABLE` for both failing conditions; **carve** rejects only `CLOSED` at rank 12 so INTAKE/PROTOCOL_PENDING surface `ERR_PROTOCOL_NOT_APPROVED`.
11. **Release privilege quota** implemented literally as `max(2, ceil(total × privilege_sample_pct))` — this does mean a batch with one privilege entry can never be released; kept because the PRD says "the greater of 2".
12. **Pace strike on submit** applied to every submit, following §3.7's unconditional wording over §3.2's "for a first-pass assignment" aside.
13. **`privilege_basis` criteria membership** enforced on authoring but not on amend (the PRD scopes that rule to the logging paragraph).
14. **SECOND_LEVEL legality** decided purely from batch status `SECOND_LEVEL`, which yields `ERR_INVALID_STATE` automatically when the protocol skipped second level.
15. **Removal re-evaluated after every scorecard event**, including `CLEARED_STRIKE`, since a clean sample can push cumulative sampled documents past 50 and trip the accuracy ground.
16. **Supersede does not double-bump the batch `version`** — `void_assignment` gained a `reset_batch` flag so the reassignment path resets/re-sets the batch exactly once.

Nothing under `test_helpers/` or `test_suite/` was read or written at any point.

## Step 7: Run tests and iterate — 2026-09-03T01:35:00.000Z

All green. Final state: **8/8 parallel rounds at 94/94 passed**, no flakiness.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each, 24 rounds total).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable, so all 94 tests survive.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` → `matter_payload()`: the default payload shipped **both** `per_document_rate_cents: 150` and `hourly_rate_cents: 6500` alongside `pricing_model: "PER_DOCUMENT"`. PRD §3.1 states "When it is `PER_DOCUMENT`, `per_document_rate_cents` is required and `hourly_rate_cents` must be omitted or null; when it is `HOURLY`, `hourly_rate_cents` is required and `per_document_rate_cents` must be omitted or null… Supplying the wrong rate for the chosen model… is rejected with `ERR_INVALID_REQUEST`." The PRD-faithful implementation correctly rejected every matter the factory built, so **88 of 94 tests died in setup**. The factory now drops whichever rate the chosen `pricing_model` forbids, unless the caller explicitly supplied it (so the shape-rule negative tests still pass both).

**Fixes applied to `test_suite/`:**
- `test_suite/test_04_transitive_cascades.py` → `test_the_third_strike_removes_the_reviewer_and_sweeps_only_unbilled_work`: asserted `accuracy_score == 0.9250` after the removal cascade. PRD §3.3 defines the accuracy sample set as samples "whose batch carries a first-pass assignment belonging to this reviewer **in any status other than `VOIDED`**", and the removal cascade the test itself asserts (`billed["status"] == "VOIDED"`) had just voided the only qualifying assignment — so no sample qualifies and PRD's own "With no qualifying samples at all, both variants return exactly 1.0000" applies. Assertion corrected to `1.0000` with the PRD quotes inline; the assertion was made more faithful, not weakened.

**Fixes applied to `implementation/`:** none. The implementation was already PRD-faithful on both defects (`services/compute.py::accuracy_sample_set` already excludes VOIDED first-pass assignments exactly as PRD §3.3 specifies).

**Load-induced non-defect (confirmed, not "fixed"):** `test_three_batches_split_two_and_one_across_the_pages` errored on setup with `RemoteDisconnected` / `ConnectionResetError` in 2 of 8 rounds of the second sweep. The endpoint under test (batch list pagination) has no timing logic; the final sweep ran it clean in all 8 rounds, so it was CPU contention on the shared host, not a defect.

Note: `workspace/implementation/results.{1..8}.json` remain on disk as the clean-sweep evidence; transient sweep scripts and round logs were removed.

**Orchestrator verification:** independently parsed all 8 `results.$i.json` — every round reports `passed=94, total=94`.

**Step 8 skip decision:** NOT skipped. Step 7 ran 3 iterations with 1 `test_helpers/` fix and 1 `test_suite/` fix, so the skip condition (zero iterations beyond baseline) does not hold. Note `implementation/` fixes are 0, so Step 8 is expected to find few or no genuine PRD silences; the two Step 7 items are candidate PRD-silence sites (the pricing-model rate-shape rule and the VOIDED-exclusion accuracy sample set) that Step 8 must check against `implementation/` before editing anything.

## Step 8: Finalize PRD — 2026-09-03T01:47:00.000Z

## Result

`workspace/PRD_FINALIZED.md` created. **Zero edits** — it is byte-identical to `PRD.md` (md5 `d5014c57…` on both).

- **Line counts:** PRD.md 515 / PRD_FINALIZED.md 515 — **0.0% delta**.
- **Change list:** none. Both `<step_7_diff>` items resolved to test-side bugs against PRD prose that already uniquely determines the implementation's behaviour, so patching would have meant inventing prose.

## Per-item pre-edit analysis (no edit committed, search still performed)

**Item 1 — `test_helpers/factories.py::matter_payload` shipping both rates**

(a) Subject: the `PER_DOCUMENT`/`HOURLY` rate shape fork on matter intake.
(b) Impl paths enumerated: `implementation/routes/matters.py:81-97` (the only writer of `pricing_model`/`per_document_rate_cents`/`hourly_rate_cents` — there is no matter-update endpoint); `implementation/validation.py:21-22` (`present()` — key-present-but-`None` counts as absent) and `:52-64` (`req_int` min-1 enforcement); `implementation/services/compute.py:583-611` (`matter_out`, echoes both rate fields, the forbidden one as `null`); downstream consumers of the fork — `compute.effective_per_document_cents:484-491` (returns 0 for non-`PER_DOCUMENT`), `compute.committed_amount_cents:494-498`, `compute.hourly_billable_cents:506-507`, `routes/matters.py:246-251` (remaining-work basis guards `per_document_rate_cents is None`).
(c) No wording adjustment, because no edit: PRD §3.1 ("When it is `PER_DOCUMENT`, `per_document_rate_cents` is required and `hourly_rate_cents` must be omitted **or null**… Supplying the wrong rate for the chosen model… is rejected with `ERR_INVALID_REQUEST`") matches `routes/matters.py:85-92` exactly, including the null-as-absent treatment. The forbidden-rate check is a pure fixture bug. Note kept but not acted on: §4's endpoint row calls both rates "optional", which is the loose wording the fixture appears to have followed; §3.1 is the explicit narrower rule, so per Method step 2 the prose stays verbatim rather than being tightened.

**Item 2 — `test_04::test_the_third_strike_removes_the_reviewer_and_sweeps_only_unbilled_work` accuracy assertion**

(a) Subject: the reviewer accuracy sample set and its value after the removal void-sweep.
(b) Impl paths enumerated: `implementation/services/compute.py:342-356` (`accuracy_sample_set` — excludes `VOIDED` first-pass assignments), `:359-363` (`accuracy_totals`), `:366-382` (both `SAMPLE_WEIGHTED` and `ASSIGNMENT_MEAN`, empty-set → `1.0000`), `:406-414` (`removal_grounds_met`, the >=50-sampled-doc accuracy ground), `:652` (`reviewer_out` always `SAMPLE_WEIGHTED`), `:463-472` (`assignment_accuracy_pct` — a *different*, per-batch set, deliberately not touched); the auto-assignment consumer and the scorecard read (`routes/reviewers.py` scorecard endpoint); cascade producers that change the set membership — `services/cascade.py:116-137` (`void_assignment`), `:152-172` (`remove_reviewer`, voids `ASSIGNED`/`IN_PROGRESS`/`REOPENED` in `created_at` order), `:204-211` (blocked-screening link 4), and `routes/qc.py:134-167` (failure cascade: `SUBMITTED → REOPENED`, `QC_FAILURE` + `PRIVILEGE_MISS`, then `evaluate_removal`).
(c) No wording adjustment, because no edit: PRD §3.3 already pins both halves the test needed — the sample set requires "a first-pass assignment belonging to this reviewer in any status other than `VOIDED`", and "With no qualifying samples at all, both variants return exactly 1.0000". The cascade order in `qc.py`/`cascade.py` makes the assignment `REOPENED` and then `VOIDED` before the read, so `1.0000` is the PRD-derivable value. `compute.py:342-356` is verbatim-faithful; the old `0.9250` assertion was the defect.

## Step 9: Complete PRD — 2026-09-03T02:07:00.000Z

Verification passed and the file is complete. Final report:

## Output
`workspace/PRD_COMPLETED.md`

**Size:** source `PRD_FINALIZED.md` 515 lines / 117,478 chars → `PRD_COMPLETED.md` 519 lines / 131,292 chars (**+4 lines, +13,814 chars**).

**Structural verification (shell-checked):** 5 top-level sections (`## 1.`–`## 5.`) present; §4 endpoint table = **57** method rows; §5 catalogue = **52** `ERR_` rows; file ends on the last catalogue row (`ERR_BUDGET_WOULD_EXCEED | 402`), a real section boundary. `diff` shows **43 changed lines + 1 inserted paragraph and zero deleted lines/hunks** — nothing was dropped.

**Totals:** 49 change sites — **11 mismatch-revisions**, **38 ambiguity-pins**.

## Changes

**§2 — Global specifications**
- §2.4 — revise — mismatch — envelope `api_request_timestamp` comes from the **real wall clock**, not the logical clock; the "nothing reads wall-clock time" claim narrowed to business logic — `response.py:23,34`
- §2.4 — insert — ambiguity — `/_clock/set_current_utc` echoes the caller's raw string verbatim; comparisons truncate to whole seconds — `routes/clock.py:18`, `db.py` `CLOCK_START_RAW`
- §2.3 — insert — ambiguity — `limit` 1–100 (default 10), `offset` >=0; out-of-range → `ERR_INVALID_REQUEST` — `response.py:87`
- §2.3 — insert — ambiguity — list filters are exact literal string matches, empty value = absent — `routes/*.py` listings
- §2.5 — insert — ambiguity — rank 5 resolves FK existence before rank 8 shape on the same field — `routes/qc.py:41-48`, `routes/assignments.py:126-130`
- §2.5 — revise — mismatch — rank 22 needs **all three** authorisations including the agreement's `remote_work_addendum` — `routes/sessions.py:76-79`
- §2.9 — insert — ambiguity — fractional figures (incl. `volume_discount_pct`) are emitted as JSON **numbers**, so trailing zeros do not survive (`1.0`, not `"1.0000"`) — `services/compute.py:77-78`
- §2.10 — revise — ambiguity — a recomputation that changes nothing does not bump `version` — `db.py` `touch()`
- §2.11 — revise — ambiguity — ledger `description` is `"{entry_type} for batch {batch_number}"` — `services/cascade.py:21`
- §2.11 — revise — mismatch — the `REMOVAL` note is `"Reviewer removed from engagement at N strikes."` and names no batch — `services/cascade.py:156`

**§3.1–3.2 — Matters, protocols**
- §3.1 — insert — ambiguity — client read is role-gated only, no ownership scoping — `routes/clients.py:42-47`
- §3.1 — insert — ambiguity — `deadline_utc` stored/echoed verbatim, compared at whole-second resolution, not required to be future at intake — `routes/matters.py`
- §3.1 — insert — ambiguity — `suspension_reason` <=500 chars, written null when omitted — `routes/matters.py`
- §3.1 — insert — ambiguity — illegal suspend/resume → `ERR_INVALID_STATE` — `routes/matters.py`
- §3.2 — insert — mismatch — protocol-reading rules fall back to the most recently **approved** (even superseded) revision — `services/compute.py:264`
- §3.2 — insert — ambiguity — `change_notes` 1–2000 chars; validated then discarded on `APPROVE` — `routes/protocols.py:140-151`

**§3.3–3.5 — Reviewers, screenings, agreements, sessions**
- §3.3 — revise — ambiguity — reviewer `pace_dph` pools documents/minutes over `SUBMITTED|COMPLETED` — `services/compute.py:385`
- §3.3 — revise — ambiguity — scorecard `sampled_document_count`/`total_error_count` are pooled totals under either weighting; bad `weighting` → `ERR_INVALID_REQUEST`, empty = default — `routes/reviewers.py:143-155`
- §3.3 — insert — ambiguity — `UNVERIFIED` is never a reachable target; rank-12 state check precedes rank-14 `ERR_REVIEWER_REMOVED` — `routes/reviewers.py:104-116`
- §3.4 — revise — ambiguity — `decision_note` overwritten to null when omitted — `routes/screenings.py`
- §3.4 — insert — ambiguity — adverse-party-is-client → `ERR_INVALID_STATE` at rank 12, ahead of the suspension check — `routes/screenings.py`
- §3.4 — insert — ambiguity — waiver ruling is not suspension-gated; note null when omitted — `routes/screenings.py`
- §3.5 — revise — ambiguity — `signature_name` 1–120 chars; elapsed coverage → `ERR_INVALID_STATE` — `routes/agreements.py`
- §3.5 — revise — mismatch — `STAFFING → IN_REVIEW` also requires a currently `APPROVED` protocol; the downward move does not; only those two statuses are ever moved — `services/cascade.py:43-53`
- §3.5 — revise — ambiguity — activation outside the session's own window → `ERR_INVALID_STATE`; close also requires the matter not `SUSPENDED` — `routes/sessions.py:172-182`

**§3.6 — Batches and assignments**
- §3.6 — revise — mismatch — `priority_rank` is advisory only; nothing orders by it (the asserted tie-break does not exist) — `routes/batches.py:39,70`
- §3.6 — revise — ambiguity — `CLOSED` matter → `ERR_INVALID_STATE` first; `document_count` 0 → `ERR_ZERO_DOCUMENT_BATCH`, negative → `ERR_INVALID_REQUEST` at rank 8 — `routes/batches.py:38-54`
- §3.6 — insert — ambiguity — dissolve carries no suspension or protocol condition — `routes/batches.py:106-124`
- §3.6 — revise — mismatch — only a `FIRST_PASS` create moves the batch status; `SECOND_LEVEL` leaves it in `SECOND_LEVEL` but still bumps `version` — `routes/assignments.py:112-114`
- §3.6 — insert — ambiguity — new paragraph pinning the rank-12 batch-status gate for all four create/supersede combinations, `ERR_INVALID_STATE` otherwise, shared by both create paths — `routes/assignments.py:43-59`
- §3.6 — revise — mismatch — supersede preconditions are pass-type dependent (`ASSIGNED|IN_PROGRESS` for first pass, `SECOND_LEVEL` for second) — `routes/assignments.py:43-59`
- §3.6 — revise — mismatch — the incoming create (not the void) sets the batch back to `ASSIGNED`; a second-level supersede leaves `SECOND_LEVEL` — `routes/assignments.py:85-114`
- §3.6 — insert — ambiguity — the budget ceiling is tested **before** the supersede reversal, so a reassignment must fit alongside the row it replaces — `routes/assignments.py:79-87`
- §3.6 — insert — ambiguity — auto-assign language/subject ratios are exactly 0 when the matter's list is empty — `routes/assignments.py:226-237`
- §3.6 — revise — ambiguity — `void_reason` mandatory free text 1–200 chars; void has no suspension or ownership condition — `routes/assignments.py:507-511`

**§3.7 — Coding and submission**
- §3.7 — insert — ambiguity — start bumps the batch `version` only when the batch status actually moves — `routes/assignments.py:383-385`
- §3.7 — insert — ambiguity — omitted `privilege_hits_logged` retains the stored value — `routes/assignments.py:399-400`
- §3.7 — revise — mismatch — `pace_dph` is **never frozen**; always derived from stored counters — `services/compute.py:456-460`
- §3.7 — revise — mismatch — the pace comparison uses the *effective* protocol (approved-fallback), 0 where none ever existed — `routes/assignments.py:478-480`
- §3.7 — insert — ambiguity — privilege logging's only state condition is the `ACTIVE` session: no assignment, batch-status, suspension or approved-protocol gate — `routes/privilege.py:35-53`

**§3.8 — QC, privilege validation, release**
- §3.8 — revise — ambiguity — draw order: batch status → suspension → `ERR_PROTOCOL_NOT_APPROVED` → segregation of duties — `routes/qc.py:50-60`
- §3.8 — revise — ambiguity — negative error counts → `ERR_INVALID_REQUEST`; validate requires non-suspended, no batch-status gate; threshold 0 with no approved revision ⇒ always `FAILED` — `routes/qc.py:110-131`
- §3.8 — insert — ambiguity — a clean `PASSED` sample also runs the removal evaluation (accuracy limb can still remove); skipped entirely with no non-voided first pass — `routes/qc.py:139-147`
- §3.8 — revise — ambiguity — failure cascade: strike appended whatever the first-pass status; whole cascade skipped when no non-voided first pass exists — `routes/qc.py:134-166`
- §3.8 — revise — ambiguity — the quota floor of 2 is uncapped, so a batch with 0 or 1 privilege entries can never be released — `services/compute.py:444-450`
- §3.8 — revise — ambiguity — release requires non-suspended plus a currently `APPROVED` protocol, before the quota — `routes/batches.py:133-136`
- §3.8 — revise — ambiguity — the `→ QC_CLOSEOUT` continuation is attempted only from `IN_REVIEW` — `routes/batches.py:162-167`

**§3.9 and §5**
- §3.9 — insert — ambiguity — `HOURLY` matter ⇒ contract rate 0 ⇒ `remaining_work_basis_cents` 0 — `routes/matters.py:246-251`
- §3.9 — insert — ambiguity — invalid `basis` → `ERR_INVALID_REQUEST`, empty = omitted; both bases and the full waterfall are always returned — `routes/matters.py:224-290`
- §5 — insert — ambiguity — new paragraph for the out-of-catalogue fallbacks `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, unparseable body → `ERR_INVALID_REQUEST` 422, `ERR_INTERNAL` otherwise — `app.py:48-59`

**Notable findings worth flagging to the caller:** two impl behaviours were outright unreachable-but-real (`STAFFING → IN_REVIEW` protocol guard; close-while-suspended), and three were substantive contradictions of PRD prose rather than gaps — `priority_rank` ordering that no code performs, the "frozen `pace_dph`" that is in fact always derived, and the wall-clock envelope timestamp in a system that otherwise reads only the logical clock.

**Orchestrator verification:** independently confirmed `PRD_COMPLETED.md` = 519 lines, 5 top-level sections, 57 endpoint rows, 52 `ERR_` catalogue rows, tail ends on the final complete table row. No truncation.

---

## Pipeline complete — 2026-09-03T02:07:00.000Z

All nine steps finished. Final state: 94/94 tests passing in all 8 parallel sweep rounds; `workspace/PRD_COMPLETED.md` written.
