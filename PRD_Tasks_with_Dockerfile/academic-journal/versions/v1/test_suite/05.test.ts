import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope, createReviewAssignmentPayload, createReviewInvitationPayload, Journal,
  Manuscript,
  ReviewAssignment, Review,
  UserRole,
  ApiErrorId,
  ReviewStatus,
  setupJournal, setupManuscript,
  setupReviewerProfile,
  JournalStatus,
  ManuscriptStatus,
  ReviewAssignmentStatus,
  setupInvitedReview,
  setupAcceptedReview
} from '../../../test-helpers';

async function setupJournalWithManuscriptsInReview(
  journalOverrides: Partial<{ total_prestige: number }> = {},
  manuscriptOverrides: Partial<{ is_fast_track_submission: boolean; title: string }> = {}
): Promise<{ journal: Journal; manuscript: Manuscript }> {
  const editorHeaders = buildUserHeaders('editor-setup', UserRole.JournalEditor);

  const journal = await setupJournal(journalOverrides);

  const manuscript = await setupManuscript(journal.id, manuscriptOverrides);

  const inReviewRes = await apiClient.beginReview(journal.id, editorHeaders);
  const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

  return { journal: inReviewJournal, manuscript };
}

describe('Phase 5: Edge Cases and Complex Interactions', () => {
  const journalEditorHeaders = buildUserHeaders('jour-editor-5', UserRole.JournalEditor);
  const sectionEditorHeaders = buildUserHeaders('sect-editor-5', UserRole.SectionEditor);
  const managingEditorHeaders = buildUserHeaders('mana-editor-5', UserRole.ManagingEditor);

  it('should increase risk score for an extra revision cycle and restore it on cancellation', async () => {
    const { journal, manuscript } = await setupJournalWithManuscriptsInReview({ total_prestige: 100 });
    const reviewer = await setupReviewerProfile(journal.id);

    for (let i = 0; i < 3; i++) {
      const assignment = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
      const review = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));
      await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
    }

    const journalAfterInitialReviews = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalAfterInitialReviews.desk_reject_risk_score).toBe(0);

    const extraAssignment = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const extraReview = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(extraAssignment.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));

    const journalAfterPenalty = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalAfterPenalty.desk_reject_risk_score).toBe(20);

    await apiClient.cancelReview(journal.id, extraReview.id, journalEditorHeaders);

    const journalAfterCancellation = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalAfterCancellation.desk_reject_risk_score).toBe(0);
  });

  it('should clamp risk score at zero and not allow it to be negative', async () => {
    const { journal, manuscript } = await setupJournalWithManuscriptsInReview(
      { total_prestige: 100 },
      { is_fast_track_submission: true }
    );
    expect(journal.desk_reject_risk_score).toBe(5);

    const journalAfterFastTrack = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalAfterFastTrack.desk_reject_risk_score).toBe(5);

    const reviewer = await setupReviewerProfile(journal.id);

    const regularReviews = [];
    for (let i = 0; i < 3; i++) {
      const assignment = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
      const review = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));
      await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
      regularReviews.push(review);
    }

    const extraAssignment = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const extraReview = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(extraAssignment.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));

    const journalAfterExtraReview = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalAfterExtraReview.desk_reject_risk_score).toBe(25);

    await apiClient.cancelReview(journal.id, extraReview.id, journalEditorHeaders);

    const journalAfterFirstCancel = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalAfterFirstCancel.desk_reject_risk_score).toBe(5);

    await apiClient.cancelReview(journal.id, regularReviews[0].id, journalEditorHeaders);

    const journalAfterSecondCancel = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalAfterSecondCancel.desk_reject_risk_score).toBe(5);
  });

  it('should allow reading manuscripts from an ARCHIVED journal', async () => {
    const { journal, manuscript } = await setupJournalWithManuscriptsInReview({ total_prestige: 10 });

    await apiClient.initiatePublication(journal.id, journalEditorHeaders);
    await apiClient.finalizePublication(journal.id, managingEditorHeaders);

    const archivedJournal = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(archivedJournal.status).toBe(JournalStatus.ARCHIVED);

    const manuscriptsRes = await apiClient.getManuscripts(journal.id, journalEditorHeaders);
    const manuscripts = handleApiResponse<Manuscript[]>(manuscriptsRes, 200, { expectPaginated: true });
    expect(manuscripts.length).toBe(1);
    expect(manuscripts[0].id).toBe(manuscript.id);
  });

  it('should allow reading reviews from a journal in ACCEPTING_SUBMISSIONS state', async () => {
    const journal = await setupJournal();
    expect(journal.status).toBe(JournalStatus.ACCEPTING_SUBMISSIONS);

    const reviewsRes = await apiClient.getReviews(journal.id, sectionEditorHeaders);
    const reviews = handleApiResponse<Review[]>(reviewsRes, 200, { expectPaginated: true });
    expect(reviews).toEqual([]);
  });

  it('should reject review invitation when reviewer is missing required expertise', async () => {
    const { journal, manuscript } = await setupJournalWithManuscriptsInReview();
    const assignment = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload({ required_expertise: 'Quantum Physics' }), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const reviewer = await setupReviewerProfile(journal.id, { expertise_areas: ['Feline Psychology'] });

    const reviewRes = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders);
    validateErrorEnvelope(reviewRes, { expectedErrorId: ApiErrorId.ERR_EXPERTISE_MISMATCH });
  });

  it('should reopen assignment when review is cancelled without affecting manuscript status', async () => {
    const { journal, manuscript, review } = await setupAcceptedReview();

    await apiClient.updateManuscript(journal.id, manuscript.id, { status: ManuscriptStatus.PENDING_REVIEW }, journalEditorHeaders);

    const readyManuscript = await apiClient.getManuscript(journal.id, manuscript.id, journalEditorHeaders).then(r => handleApiResponse<Manuscript>(r, 200));
    expect(readyManuscript.status).toBe(ManuscriptStatus.PENDING_REVIEW);

    await apiClient.cancelReview(journal.id, review.id, journalEditorHeaders);

    const assignmentCheckRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, review.assignment_id, sectionEditorHeaders);
    const reopenedAssignment = handleApiResponse<ReviewAssignment>(assignmentCheckRes, 200);
    expect(reopenedAssignment.status).toBe(ReviewAssignmentStatus.PENDING_ASSIGNMENT);

    const manuscriptAfterCancel = await apiClient.getManuscript(journal.id, manuscript.id, journalEditorHeaders).then(r => handleApiResponse<Manuscript>(r, 200));
    expect(manuscriptAfterCancel.status).toBe(ManuscriptStatus.PENDING_REVIEW);

    const acceptRes = await apiClient.updateManuscript(journal.id, manuscript.id, { status: ManuscriptStatus.ACCEPTED }, journalEditorHeaders);
    const acceptedManuscript = handleApiResponse<Manuscript>(acceptRes, 200);
    expect(acceptedManuscript.status).toBe(ManuscriptStatus.ACCEPTED);
  });

  it('should cascade cancellation from manuscript and revert ledger entries', async () => {
    const editorHeaders = buildUserHeaders('editor-cascade', UserRole.JournalEditor);
    const journal = await setupJournal({ total_prestige: 200 });

    const baselineManuscript = await setupManuscript(journal.id, { title: 'Baseline Manuscript' });
    const manuscriptToCancel = await setupManuscript(journal.id, { title: 'Manuscript to Cancel', is_fast_track_submission: true });

    const inReviewRes = await apiClient.beginReview(journal.id, editorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const reviewer = await setupReviewerProfile(inReviewJournal.id);
    const assignment1 = await apiClient.createReviewAssignment(inReviewJournal.id, baselineManuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment1.id, reviewer.id), sectionEditorHeaders);

    const journalStateBefore = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    const prestigeBefore = journalStateBefore.prestige_balance;
    const riskBefore = journalStateBefore.desk_reject_risk_score;
    expect(riskBefore).toBe(5);

    const assignmentToCancel = await apiClient.createReviewAssignment(inReviewJournal.id, manuscriptToCancel.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const reviewToCancel = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignmentToCancel.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));

    const journalStateAfter = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalStateAfter.desk_reject_risk_score).toBe(riskBefore);
    expect(journalStateAfter.prestige_balance).toBeLessThan(prestigeBefore);

    await apiClient.updateManuscript(inReviewJournal.id, manuscriptToCancel.id, { status: ManuscriptStatus.REJECTED }, journalEditorHeaders);

    const cancelledReview = await apiClient.getReview(inReviewJournal.id, reviewToCancel.id, journalEditorHeaders).then(r => handleApiResponse<Review>(r, 200));
    expect(cancelledReview.status).toBe(ReviewStatus.CANCELLED);

    const finalJournalState = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(finalJournalState.prestige_balance).toBeCloseTo(prestigeBefore);
    expect(finalJournalState.desk_reject_risk_score).toBe(0);
  });

  it('should correctly revert prestige and risk score when declining a review for an extra revision cycle', async () => {
    const { journal, manuscript } = await setupJournalWithManuscriptsInReview({ total_prestige: 100 });
    const reviewer = await setupReviewerProfile(journal.id);

    for (let i = 0; i < 3; i++) {
      const assignment = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
      const review = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));
      await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
    }

    const journalBefore = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    const prestigeBefore = journalBefore.prestige_balance;
    const riskBefore = journalBefore.desk_reject_risk_score;

    const extraAssignment = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const extraReview = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(extraAssignment.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));

    const journalAfterInvite = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalAfterInvite.prestige_balance).toBeLessThan(prestigeBefore);
    expect(journalAfterInvite.desk_reject_risk_score).toBe(riskBefore + 20);

    await apiClient.declineReview(journal.id, extraReview.id, journalEditorHeaders);

    const journalAfterDecline = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalAfterDecline.prestige_balance).toBeCloseTo(prestigeBefore);
    expect(journalAfterDecline.desk_reject_risk_score).toBe(riskBefore);
  });

  it('should fail to submit a review if it is not ACCEPTED', async () => {
    const { journal, review } = await setupInvitedReview();

    const submitRes = await apiClient.submitReview(journal.id, review.id, journalEditorHeaders);
    validateErrorEnvelope(submitRes, { expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID });

    await apiClient.declineReview(journal.id, review.id, journalEditorHeaders);
    const submitAgainRes = await apiClient.submitReview(journal.id, review.id, journalEditorHeaders);
    validateErrorEnvelope(submitAgainRes, { expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID });
  });

  describe('Operations on an ARCHIVED journal are rejected', () => {
    let archivedJournal: Journal;
    let manuscriptInArchivedJournal: Manuscript;

    beforeEach(async () => {
      const result = await setupJournalWithManuscriptsInReview({ total_prestige: 10 });
      manuscriptInArchivedJournal = result.manuscript;
      await apiClient.initiatePublication(result.journal.id, journalEditorHeaders);
      const finalizationRes = await apiClient.finalizePublication(result.journal.id, managingEditorHeaders);
      archivedJournal = handleApiResponse<Journal>(finalizationRes, 200);
      expect(archivedJournal.status).toBe(JournalStatus.ARCHIVED);
    });

    it('should fail to create a review assignment in an ARCHIVED journal', async () => {
      const assignmentRes = await apiClient.createReviewAssignment(archivedJournal.id, manuscriptInArchivedJournal.id, createReviewAssignmentPayload(), sectionEditorHeaders);
      validateErrorEnvelope(assignmentRes, { expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_IN_REVIEW });
    });
  });

  it('should return risk error when risk threshold and prestige are both breached', async () => {
    const editorHeaders = buildUserHeaders('editor-risk', UserRole.JournalEditor);
    const journal = await setupJournal({ total_prestige: 50 });

    const manuscript = await setupManuscript(journal.id);
    const fastTrackManuscripts = [];
    for (let i = 0; i < 4; i++) {
      const m = await setupManuscript(journal.id, { is_fast_track_submission: true });
      fastTrackManuscripts.push(m);
    }
    const extraManuscript = await setupManuscript(journal.id);

    for (let i = 0; i < 14; i++) {
      await setupManuscript(journal.id, { is_fast_track_submission: true });
    }
    const highRiskManuscript = await setupManuscript(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, editorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    for (let i = 0; i < 4; i++) {
      const reviewer = await setupReviewerProfile(inReviewJournal.id);
      const a = await apiClient.createReviewAssignment(inReviewJournal.id, fastTrackManuscripts[i].id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
      const r = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(a.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));
      await apiClient.acceptReview(inReviewJournal.id, r.id, journalEditorHeaders);
    }

    const extraReviewer = await setupReviewerProfile(inReviewJournal.id);
    for (let i = 0; i < 3; i++) {
      const assignment = await apiClient.createReviewAssignment(inReviewJournal.id, extraManuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
      const review = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment.id, extraReviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));
      await apiClient.acceptReview(inReviewJournal.id, review.id, journalEditorHeaders);
    }

    const journalState = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(journalState.prestige_balance).toBe(43);
    expect(journalState.desk_reject_risk_score).toBe(90);

    const conflictingAssignment = await apiClient.createReviewAssignment(inReviewJournal.id, extraManuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const newReviewer = await setupReviewerProfile(inReviewJournal.id);
    const reviewRes = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(conflictingAssignment.id, newReviewer.id), sectionEditorHeaders);

    validateErrorEnvelope(reviewRes, { expectedErrorId: ApiErrorId.ERR_RISK_THRESHOLD_BREACHED });
  });

  it('should have the journal risk score reflect ledger changes immediately', async () => {
    const editorHeaders = buildUserHeaders('editor-ledger', UserRole.JournalEditor);
    const journal = await setupJournal({ total_prestige: 500 });

    const manuscript1 = await setupManuscript(journal.id, { is_fast_track_submission: true });
    const manuscript2 = await setupManuscript(journal.id);

    const inReviewRes = await apiClient.beginReview(journal.id, editorHeaders);
    const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

    const reviewer = await setupReviewerProfile(inReviewJournal.id);

    const state0 = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(state0.desk_reject_risk_score).toBe(5);

    await apiClient.updateManuscript(inReviewJournal.id, manuscript1.id, { status: ManuscriptStatus.REJECTED }, journalEditorHeaders);
    const state2 = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(state2.desk_reject_risk_score).toBe(0);

    for (let i = 0; i < 3; i++) {
      const assignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript2.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
      await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders);
    }
    const state3 = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(state3.desk_reject_risk_score).toBe(0);

    const extraAssignment = await apiClient.createReviewAssignment(inReviewJournal.id, manuscript2.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const extraReview = await apiClient.inviteReviewer(inReviewJournal.id, createReviewInvitationPayload(extraAssignment.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));
    const state4 = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(state4.desk_reject_risk_score).toBe(20);

    await apiClient.cancelReview(inReviewJournal.id, extraReview.id, journalEditorHeaders);
    const state5 = await apiClient.getJournal(inReviewJournal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
    expect(state5.desk_reject_risk_score).toBe(0);
  });

  it('should correctly revert prestige costs for reviews in different states when rejecting manuscript', async () => {
    const { journal, manuscript } = await setupJournalWithManuscriptsInReview({ total_prestige: 100 });
    const reviewer1 = await setupReviewerProfile(journal.id);
    const reviewer2 = await setupReviewerProfile(journal.id);
    const reviewer3 = await setupReviewerProfile(journal.id);

    const initialPrestige = (await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200))).prestige_balance;

    const assignment1 = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const review1 = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment1.id, reviewer1.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));

    const assignment2 = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const review2 = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment2.id, reviewer2.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));
    await apiClient.acceptReview(journal.id, review2.id, journalEditorHeaders);

    const assignment3 = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
    const review3 = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment3.id, reviewer3.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));
    await apiClient.acceptReview(journal.id, review3.id, journalEditorHeaders);
    await apiClient.submitReview(journal.id, review3.id, journalEditorHeaders);

    const prestigeAfterReviews = (await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200))).prestige_balance;
    expect(prestigeAfterReviews).toBeLessThan(initialPrestige);

    await apiClient.updateManuscript(journal.id, manuscript.id, { status: ManuscriptStatus.REJECTED }, journalEditorHeaders);

    const finalPrestige = (await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200))).prestige_balance;
    expect(finalPrestige).toBe(initialPrestige);
  });

  it('should correctly revert risk penalties from extra revision cycles when rejecting manuscript', async () => {
    const { journal, manuscript } = await setupJournalWithManuscriptsInReview({ total_prestige: 100 });
    const reviewer = await setupReviewerProfile(journal.id);

    const initialRisk = (await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200))).desk_reject_risk_score;

    for (let i = 0; i < 4; i++) {
      const assignment = await apiClient.createReviewAssignment(journal.id, manuscript.id, createReviewAssignmentPayload(), sectionEditorHeaders).then(r => handleApiResponse<ReviewAssignment>(r, 201));
      const review = await apiClient.inviteReviewer(journal.id, createReviewInvitationPayload(assignment.id, reviewer.id), sectionEditorHeaders).then(r => handleApiResponse<Review>(r, 201));
      if (i < 3) {
        await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
      }
    }

    const riskAfterExtraReview = (await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200))).desk_reject_risk_score;
    expect(riskAfterExtraReview).toBe(initialRisk + 20);

    await apiClient.updateManuscript(journal.id, manuscript.id, { status: ManuscriptStatus.REJECTED }, journalEditorHeaders);

    const finalRisk = (await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200))).desk_reject_risk_score;
    expect(finalRisk).toBe(initialRisk);
  });
});
