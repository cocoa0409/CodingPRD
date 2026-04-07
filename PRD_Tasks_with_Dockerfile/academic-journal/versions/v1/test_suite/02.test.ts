import {
    apiClient,
    buildUserHeaders, handleApiResponse,
    validateErrorEnvelope,
    ApiErrorId,
    UserRole,
    Journal,
    JournalStatus,
    Manuscript,
    ManuscriptStatus,
    ReviewAssignment,
    ReviewAssignmentStatus,
    Review,
    ReviewStatus,
    setupJournal,
    setupJournalInReview,
    setupManuscript,
    setupReviewerProfile,
    setupInvitedReview,
    setupAcceptedReview,
    setupBasicJournalScenario,
    assertJournal,
    assertManuscript, createReviewAssignmentPayload
} from '../../../test-helpers';
import { v4 as uuidv4 } from 'uuid';

describe('Phase 2: State Machine Transitions', () => {
    const journalEditorHeaders = buildUserHeaders('editor-1', UserRole.JournalEditor);
    const sectionEditorHeaders = buildUserHeaders('se-1', UserRole.SectionEditor);
    const managingEditorHeaders = buildUserHeaders('me-1', UserRole.ManagingEditor);

    describe('Journal State Machine', () => {
        describe('Transition: begin_review_cycle (ACCEPTING_SUBMISSIONS -> IN_REVIEW)', () => {
            it('should transition journal from ACCEPTING_SUBMISSIONS to IN_REVIEW upon beginning review', async () => {
                const journal = await setupJournal();
                expect(journal.status).toBe(JournalStatus.ACCEPTING_SUBMISSIONS);

                const reviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
                const inReviewJournal = handleApiResponse<Journal>(reviewRes, 200);

                assertJournal(inReviewJournal);
                expect(inReviewJournal.status).toBe(JournalStatus.IN_REVIEW);

                const getRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const retrievedJournal = handleApiResponse<Journal>(getRes, 200);
                expect(retrievedJournal.status).toBe(JournalStatus.IN_REVIEW);
            });
        });

        describe('Transition: initiate_publication (IN_REVIEW -> PUBLICATION_PENDING)', () => {
            it('should transition journal from IN_REVIEW to PUBLICATION_PENDING when all reviews are resolved', async () => {
                const journal = await setupJournalInReview();
                expect(journal.status).toBe(JournalStatus.IN_REVIEW);

                const pubRes = await apiClient.initiatePublication(journal.id, journalEditorHeaders);
                const pubPendingJournal = handleApiResponse<Journal>(pubRes, 200);

                assertJournal(pubPendingJournal);
                expect(pubPendingJournal.status).toBe(JournalStatus.PUBLICATION_PENDING);

                const getRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const retrievedJournal = handleApiResponse<Journal>(getRes, 200);
                expect(retrievedJournal.status).toBe(JournalStatus.PUBLICATION_PENDING);
            });

            it('should fail to initiate publication if an unresolved (invited) review exists', async () => {
                const { journal } = await setupInvitedReview();
                expect(journal.status).toBe(JournalStatus.IN_REVIEW);

                const pubRes = await apiClient.initiatePublication(journal.id, journalEditorHeaders);
                validateErrorEnvelope(pubRes, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_REVIEWS_EXIST });

                const getRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const retrievedJournal = handleApiResponse<Journal>(getRes, 200);
                expect(retrievedJournal.status).toBe(JournalStatus.IN_REVIEW);
            });

            it('should fail to initiate publication if an unresolved (accepted) review exists', async () => {
                const { journal } = await setupAcceptedReview();
                expect(journal.status).toBe(JournalStatus.IN_REVIEW);

                const pubRes = await apiClient.initiatePublication(journal.id, journalEditorHeaders);
                validateErrorEnvelope(pubRes, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_REVIEWS_EXIST });

                const getRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const retrievedJournal = handleApiResponse<Journal>(getRes, 200);
                expect(retrievedJournal.status).toBe(JournalStatus.IN_REVIEW);
            });
        });

        describe('Transition: finalize_publication (PUBLICATION_PENDING -> ARCHIVED)', () => {
            it('should transition journal to ARCHIVED and submitted reviews to PUBLISHED when publication is finalized', async () => {
                const { journal, review } = await setupAcceptedReview();
                await apiClient.submitReview(journal.id, review.id, journalEditorHeaders);
                await apiClient.initiatePublication(journal.id, journalEditorHeaders);

                const getRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const pubPendingJournal = handleApiResponse<Journal>(getRes, 200);
                expect(pubPendingJournal.status).toBe(JournalStatus.PUBLICATION_PENDING);

                const finalizeRes = await apiClient.finalizePublication(journal.id, managingEditorHeaders);
                const archivedJournal = handleApiResponse<Journal>(finalizeRes, 200);

                assertJournal(archivedJournal);
                expect(archivedJournal.status).toBe(JournalStatus.ARCHIVED);

                const finalGetRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const retrievedJournal = handleApiResponse<Journal>(finalGetRes, 200);
                expect(retrievedJournal.status).toBe(JournalStatus.ARCHIVED);

                const finalReviewRes = await apiClient.getReview(journal.id, review.id, journalEditorHeaders);
                const finalReview = handleApiResponse<Review>(finalReviewRes, 200);
                expect(finalReview.status).toBe(ReviewStatus.PUBLISHED);
            });

            it('should fail with conflict error when finalizing publication for a journal still in IN_REVIEW state', async () => {
                const journal = await setupJournalInReview();
                expect(journal.status).toBe(JournalStatus.IN_REVIEW);

                const finalizeRes = await apiClient.finalizePublication(journal.id, managingEditorHeaders);

                validateErrorEnvelope(finalizeRes, {
                    expectedErrorId: ApiErrorId.ERR_JOURNAL_NOT_PENDING_PUBLICATION
                });

                const getRes = await apiClient.getJournal(journal.id, journalEditorHeaders);
                const finalJournal = handleApiResponse<Journal>(getRes, 200);
                expect(finalJournal.status).toBe(JournalStatus.IN_REVIEW);
            });
        });
    });

    describe('Manuscript State Machine', () => {
        describe('Transition: mark_ready_for_review (DRAFT -> PENDING_REVIEW)', () => {
            it('should transition manuscript and deduct prestige cost when marked as ready', async () => {
                const journal = await setupJournal({ total_prestige: 100 });
                const manuscript = await setupManuscript(journal.id);
                await setupReviewerProfile(journal.id);

                const inReviewRes = await apiClient.beginReview(journal.id, journalEditorHeaders);
                const inReviewJournal = handleApiResponse<Journal>(inReviewRes, 200);

                const assignmentPayload = createReviewAssignmentPayload();
                await apiClient.createReviewAssignment(
                    inReviewJournal.id,
                    manuscript.id,
                    assignmentPayload,
                    sectionEditorHeaders
                );

                expect(manuscript.status).toBe(ManuscriptStatus.DRAFT);
                const journalBeforeUpdate = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));

                const updateRes = await apiClient.updateManuscript(
                    inReviewJournal.id,
                    manuscript.id,
                    { status: ManuscriptStatus.PENDING_REVIEW },
                    journalEditorHeaders
                );
                const readyManuscript = handleApiResponse<Manuscript>(updateRes, 200);

                assertManuscript(readyManuscript);
                expect(readyManuscript.status).toBe(ManuscriptStatus.PENDING_REVIEW);

                const journalAfterUpdate = await apiClient.getJournal(journal.id, journalEditorHeaders).then(r => handleApiResponse<Journal>(r, 200));
                expect(journalAfterUpdate.prestige_balance).toBe(journalBeforeUpdate.prestige_balance - 10);

                const getRes = await apiClient.getManuscript(journal.id, manuscript.id, journalEditorHeaders);
                const retrievedManuscript = handleApiResponse<Manuscript>(getRes, 200);
                expect(retrievedManuscript.status).toBe(ManuscriptStatus.PENDING_REVIEW);
            });

            it('should fail trying to mark a rejected manuscript as ready for review', async () => {
                const journal = await setupJournal();
                const manuscript = await setupManuscript(journal.id);

                const rejectRes = await apiClient.updateManuscript(
                    journal.id,
                    manuscript.id,
                    { status: ManuscriptStatus.REJECTED },
                    journalEditorHeaders
                );
                const rejectedManuscript = handleApiResponse<Manuscript>(rejectRes, 200);
                expect(rejectedManuscript.status).toBe(ManuscriptStatus.REJECTED);

                const updateRes = await apiClient.updateManuscript(
                    journal.id,
                    manuscript.id,
                    { status: ManuscriptStatus.PENDING_REVIEW },
                    journalEditorHeaders
                );

                validateErrorEnvelope(updateRes, {
                    expectedErrorId: ApiErrorId.ERR_MANUSCRIPT_LIFECYCLE_STATE_INVALID
                });

                const getRes = await apiClient.getManuscript(journal.id, manuscript.id, journalEditorHeaders);
                const finalManuscript = handleApiResponse<Manuscript>(getRes, 200);
                expect(finalManuscript.status).toBe(ManuscriptStatus.REJECTED);
            });
        });
    });

    describe('ReviewAssignment State Machine', () => {

        describe('Transition: invite_reviewer (PENDING_ASSIGNMENT -> INVITED)', () => {
            it('should transition assignment from PENDING_ASSIGNMENT to INVITED when reviewer is invited', async () => {
                const { journal, manuscript, reviewer, assignment } = await setupBasicJournalScenario();
                expect(assignment.status).toBe(ReviewAssignmentStatus.PENDING_ASSIGNMENT);

                await apiClient.inviteReviewer(journal.id, { assignment_id: assignment.id, reviewer_id: reviewer.id }, sectionEditorHeaders);

                const getRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const invitedAssignment = handleApiResponse<ReviewAssignment>(getRes, 200);
                expect(invitedAssignment.status).toBe(ReviewAssignmentStatus.INVITED);
            });

            it('should fail with conflict error when inviting a reviewer to an already assigned assignment', async () => {
                const { journal, manuscript, assignment, review } = await setupAcceptedReview();

                const getAssignmentRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const assignedAssignment = handleApiResponse<ReviewAssignment>(getAssignmentRes, 200);
                expect(assignedAssignment.status).toBe(ReviewAssignmentStatus.ASSIGNED);

                const reviewer2 = await setupReviewerProfile(journal.id, { full_name: 'Reviewer Two' });

                const inviteRes = await apiClient.inviteReviewer(journal.id, { assignment_id: assignment.id, reviewer_id: reviewer2.id }, sectionEditorHeaders);

                validateErrorEnvelope(inviteRes, {
                    expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PENDING
                });

                const finalGetRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const finalAssignment = handleApiResponse<ReviewAssignment>(finalGetRes, 200);
                expect(finalAssignment.status).toBe(ReviewAssignmentStatus.ASSIGNED);
            });
        });

        describe('Transition: reopen_assignment (INVITED -> PENDING_ASSIGNMENT)', () => {
            it('should transition assignment from INVITED to PENDING_ASSIGNMENT when review is declined', async () => {
                const { journal, manuscript, assignment, review } = await setupInvitedReview();

                const invitedAssignmentRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const invitedAssignment = handleApiResponse<ReviewAssignment>(invitedAssignmentRes, 200);
                expect(invitedAssignment.status).toBe(ReviewAssignmentStatus.INVITED);

                const declineRes = await apiClient.declineReview(journal.id, review.id, journalEditorHeaders);
                expect(declineRes.status).toBe(200);

                const getRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const reopenedAssignment = handleApiResponse<ReviewAssignment>(getRes, 200);
                expect(reopenedAssignment.status).toBe(ReviewAssignmentStatus.PENDING_ASSIGNMENT);
            });

            it('should return error when declining a non-existent review', async () => {
                const { journal, manuscript, assignment } = await setupBasicJournalScenario();
                const NON_EXISTENT_UUID = uuidv4();

                const declineRes = await apiClient.declineReview(journal.id, NON_EXISTENT_UUID, journalEditorHeaders);
                validateErrorEnvelope(declineRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_NOT_FOUND
                });

                const getRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const finalAssignment = handleApiResponse<ReviewAssignment>(getRes, 200);
                expect(finalAssignment.status).toBe(ReviewAssignmentStatus.PENDING_ASSIGNMENT);
            });

            it('should fail when trying to decline an accepted review', async () => {
                const { journal, review } = await setupAcceptedReview();

                const declineRes = await apiClient.declineReview(journal.id, review.id, journalEditorHeaders);

                validateErrorEnvelope(declineRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID
                });
            });
        });

        describe('Transition: reopen_assignment (ASSIGNED -> PENDING_ASSIGNMENT)', () => {
            it('should transition assignment from ASSIGNED to PENDING_ASSIGNMENT when accepted review is cancelled', async () => {
                const { journal, manuscript, assignment, review } = await setupAcceptedReview();

                const assignedAssignmentRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const assignedAssignment = handleApiResponse<ReviewAssignment>(assignedAssignmentRes, 200);
                expect(assignedAssignment.status).toBe(ReviewAssignmentStatus.ASSIGNED);

                const cancelRes = await apiClient.cancelReview(journal.id, review.id, journalEditorHeaders);
                expect(cancelRes.status).toBe(200);

                const getRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const reopenedAssignment = handleApiResponse<ReviewAssignment>(getRes, 200);
                expect(reopenedAssignment.status).toBe(ReviewAssignmentStatus.PENDING_ASSIGNMENT);
            });
        });

        describe('Transition: confirm_review (INVITED -> ASSIGNED)', () => {
            it('should transition assignment from INVITED to ASSIGNED when review is accepted', async () => {
                const { journal, manuscript, assignment, review } = await setupInvitedReview();

                const invitedAssignmentRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const invitedAssignment = handleApiResponse<ReviewAssignment>(invitedAssignmentRes, 200);
                expect(invitedAssignment.status).toBe(ReviewAssignmentStatus.INVITED);

                const acceptRes = await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
                expect(acceptRes.status).toBe(200);

                const getRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const assignedAssignment = handleApiResponse<ReviewAssignment>(getRes, 200);
                expect(assignedAssignment.status).toBe(ReviewAssignmentStatus.ASSIGNED);
            });

            it('should fail when trying to accept a declined review', async () => {
                const { journal, manuscript, assignment, review } = await setupInvitedReview();
                await apiClient.declineReview(journal.id, review.id, journalEditorHeaders);

                const declinedReviewRes = await apiClient.getReview(journal.id, review.id, journalEditorHeaders);
                const declinedReview = handleApiResponse<Review>(declinedReviewRes, 200);
                expect(declinedReview.status).toBe(ReviewStatus.DECLINED);

                const acceptRes = await apiClient.acceptReview(journal.id, review.id, journalEditorHeaders);
                validateErrorEnvelope(acceptRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID
                });

                const finalGetRes = await apiClient.getReviewAssignment(journal.id, manuscript.id, assignment.id, sectionEditorHeaders);
                const finalAssignment = handleApiResponse<ReviewAssignment>(finalGetRes, 200);
                expect(finalAssignment.status).toBe(ReviewAssignmentStatus.PENDING_ASSIGNMENT);
            });

            it('should fail when trying to submit an invited review', async () => {
                const { journal, review } = await setupInvitedReview();

                const submitRes = await apiClient.submitReview(journal.id, review.id, journalEditorHeaders);

                validateErrorEnvelope(submitRes, {
                    expectedErrorId: ApiErrorId.ERR_REVIEW_LIFECYCLE_STATE_INVALID
                });
            });
        });
    });
});
