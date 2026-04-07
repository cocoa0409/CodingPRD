import {
  apiClient,
  buildUserHeaders,
  handleApiResponse,
  validateErrorEnvelope, createEventPayload,
  createShiftPayload,
  createStaffProfilePayload,
  createAssignmentPayload, StaffingContract,
  Event,
  Shift,
  StaffProfile,
  Assignment, EventStatus,
  ShiftStatus,
  AssignmentStatus,
  UserRole, ApiErrorId, createAndActivateContract
} from '../../../test-helpers';

describe('Phase 3: Business Logic Unit Tests', () => {
  const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
  const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);
  const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);
  describe('Rule: confirm-assignment', () => {
    describe('P3-CONFIRM-ASSIGN-01.1: Happy path confirmation', () => {
      it('should confirm assignment when cost and risk do not change', async () => {
        const contract = await createAndActivateContract();
        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const shiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload(),
          coordinatorHeaders
        );
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload(),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const assignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        );
        const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

        await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);

        const confirmRes = await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);
        const confirmedAssignment = handleApiResponse<Assignment>(confirmRes, 200);

        expect(confirmedAssignment.status).toBe(AssignmentStatus.CONFIRMED);

        const shiftCheckRes = await apiClient.getShift(contract.id, event.id, shift.id, coordinatorHeaders);
        const filledShift = handleApiResponse<Shift>(shiftCheckRes, 200);
        expect(filledShift.status).toBe(ShiftStatus.FILLED);
      });
    });

    describe('P3-CONFIRM-ASSIGN-01.2: Cannot confirm PROPOSED assignment', () => {
      it('should reject confirming assignment still in PROPOSED state', async () => {
        const contract = await createAndActivateContract();
        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const shiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload(),
          coordinatorHeaders
        );
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload(),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const assignmentRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        );
        const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

        const res = await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED });
      });
    });

    describe('P3-CONFIRM-ASSIGN-01.4.1: Rest period check on confirm ignores PROPOSED', () => {
      it('should allow confirmation even if a PROPOSED assignment causes a conflict', async () => {
        const contract = await createAndActivateContract();
        const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
        const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

        const shiftA = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700036000, end_time: 1700043200 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
        const assignA = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftA.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
        await apiClient.acceptAssignment(contract.id, assignA.id, staffMemberHeaders);

        const shiftB = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700036000, end_time: 1700043200 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
        await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftB.id, staff.id), accountManagerHeaders);

        const res = await apiClient.confirmAssignment(contract.id, assignA.id, coordinatorHeaders);
        const confirmedAssignment = handleApiResponse<Assignment>(res, 200);

        expect(confirmedAssignment.status).toBe(AssignmentStatus.CONFIRMED);
      });
    });

    describe('P3-CONFIRM-ASSIGN-01.5: Budget check on confirm', () => {
      it('should reject confirmation if recalculated OT cost exceeds budget', async () => {
        const contract = await createAndActivateContract(865.00);
        const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
        const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

        const shiftA = await apiClient.createShift(contract.id, event.id, createShiftPayload({
          start_time: 1700200000,
          end_time: 1700218000
        }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

        const assignA = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftA.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));

        expect(assignA.provisional_cost).toBe(100.00);
        expect(assignA.is_overtime_eligible).toBe(false);

        await apiClient.acceptAssignment(contract.id, assignA.id, staffMemberHeaders);

        const shiftB = await apiClient.createShift(contract.id, event.id, createShiftPayload({
          start_time: 1700000000,
          end_time: 1700136800
        }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

        const assignBRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftB.id, staff.id), accountManagerHeaders);

        validateErrorEnvelope(assignBRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
      });
    });

    describe('P3-CONFIRM-ASSIGN-01.7: Assignment loses overtime on confirmation', () => {
      it('should update cost and risk when assignment loses OT status', async () => {
        const contract = await createAndActivateContract(1000.00);
        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const shift1Res = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            start_time: 1700000000,
            end_time: 1700126000,
          }),
          coordinatorHeaders
        );
        const shift1 = handleApiResponse<Shift>(shift1Res, 201);

        const assign1Res = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift1.id, staff.id),
          accountManagerHeaders
        );
        const assign1 = handleApiResponse<Assignment>(assign1Res, 201);
        await apiClient.acceptAssignment(contract.id, assign1.id, staffMemberHeaders);

        const shift2Res = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            start_time: 1700200000,
            end_time: 1700236000,
          }),
          coordinatorHeaders
        );
        const shift2 = handleApiResponse<Shift>(shift2Res, 201);

        const assign2Res = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift2.id, staff.id),
          accountManagerHeaders
        );
        const assign2 = handleApiResponse<Assignment>(assign2Res, 201);
        await apiClient.acceptAssignment(contract.id, assign2.id, staffMemberHeaders);

        expect(assign2.is_overtime_eligible).toBe(true);
        expect(assign2.provisional_cost).toBe(250.00);

        const initialContractState = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
        expect(initialContractState.compliance_risk_score).toBe(5);

        await apiClient.cancelAssignment(contract.id, assign1.id, coordinatorHeaders);

        const confirmRes = await apiClient.confirmAssignment(contract.id, assign2.id, coordinatorHeaders);
        const confirmedAssign2 = handleApiResponse<Assignment>(confirmRes, 200);

        expect(confirmedAssign2.is_overtime_eligible).toBe(false);
        expect(confirmedAssign2.provisional_cost).toBe(200.00);

        const contractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const updatedContract = handleApiResponse<StaffingContract>(contractCheckRes, 200);
        expect(updatedContract.compliance_risk_score).toBe(0);
      });
    });

    describe('P3-CONFIRM-ASSIGN-01.12.1: Override does not bypass other validations', () => {
      it('should reject assignment for rest period violation even with override', async () => {
        const contract = await createAndActivateContract(10000.00);
        const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
        const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

        const shift1 = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000, end_time: 1700028800 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
        const assign1 = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift1.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
        await apiClient.acceptAssignment(contract.id, assign1.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, assign1.id, coordinatorHeaders);

        const shift2 = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700036000, end_time: 1700050400 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

        const res = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift2.id, staff.id, { override_risk_check: true }),
          accountManagerHeaders
        );

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION });
      });
    });

    describe('P3-CONFIRM-ASSIGN-01.13: Override without threshold breach', () => {
      it('should not apply override penalty if threshold not breached', async () => {
        const contract = await createAndActivateContract(10000.00);
        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        for (let i = 0; i < 2; i++) {
          const otherStaffRes = await apiClient.createStaffProfile(
            contract.id,
            createStaffProfilePayload({ first_name: `OTStaff${i}` }),
            coordinatorHeaders
          );
          const otherStaff = handleApiResponse<StaffProfile>(otherStaffRes, 201);

          const otShiftRes = await apiClient.createShift(
            contract.id,
            event.id,
            createShiftPayload({
              start_time: 1700000000 + (i * 150000),
              end_time: 1700000000 + (i * 150000) + 147600,
            }),
            coordinatorHeaders
          );
          const otShift = handleApiResponse<Shift>(otShiftRes, 201);

          const otAssignRes = await apiClient.createAssignment(
            contract.id,
            createAssignmentPayload(otShift.id, otherStaff.id),
            accountManagerHeaders
          );
          const otAssign = handleApiResponse<Assignment>(otAssignRes, 201);
          await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
          await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
        }

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const shift40Res = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            start_time: 1700500000,
            end_time: 1700644000,
          }),
          coordinatorHeaders
        );
        const shift40 = handleApiResponse<Shift>(shift40Res, 201);

        const assign40Res = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift40.id, staff.id),
          accountManagerHeaders
        );
        const assign40 = handleApiResponse<Assignment>(assign40Res, 201);
        await apiClient.acceptAssignment(contract.id, assign40.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, assign40.id, coordinatorHeaders);

        const preContractCheck = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
        expect(preContractCheck.compliance_risk_score).toBe(10);

        const newShiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload({
            start_time: 1700700000,
            end_time: 1700703600,
          }),
          coordinatorHeaders
        );
        const newShift = handleApiResponse<Shift>(newShiftRes, 201);

        const res = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(newShift.id, staff.id, { override_risk_check: true }),
          accountManagerHeaders
        );
        const assignment = handleApiResponse<Assignment>(res, 201);

        expect(assignment.risk_override_penalty_applied).toBe(false);

        const contractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const updatedContract = handleApiResponse<StaffingContract>(contractCheckRes, 200);
        expect(updatedContract.compliance_risk_score).toBe(15);
      });
    });
  });

  describe('Rule: check-event-readiness', () => {
    describe('P3-EVENT-READY-01.1: Mark event ready when all shifts filled', () => {
      it('should allow marking event ready when all shifts are filled', async () => {
        const contract = await createAndActivateContract();
        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const shiftRes = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload(),
          coordinatorHeaders
        );
        const shift = handleApiResponse<Shift>(shiftRes, 201);

        const staffRes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload(),
          coordinatorHeaders
        );
        const staff = handleApiResponse<StaffProfile>(staffRes, 201);

        const assignRes = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        );
        const assignment = handleApiResponse<Assignment>(assignRes, 201);
        await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

        const updateRes = await apiClient.updateEventStatus(
          contract.id,
          event.id,
          { status: EventStatus.READY_FOR_EXECUTION },
          coordinatorHeaders
        );
        const updatedEvent = handleApiResponse<Event>(updateRes, 200);

        expect(updatedEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);
      });
    });

    describe('P3-EVENT-READY-01.2: Cannot mark ready with no shifts', () => {
      it('should reject marking event ready when it has no shifts', async () => {
        const contract = await createAndActivateContract();
        const eventRes = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        );
        const event = handleApiResponse<Event>(eventRes, 201);

        const res = await apiClient.updateEventStatus(
          contract.id,
          event.id,
          { status: EventStatus.READY_FOR_EXECUTION },
          coordinatorHeaders
        );

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SHIFTS_NOT_FILLED });
      });
    });

    describe('P3-EVENT-READY-01.3: Cannot re-mark event as ready', () => {
      it('should reject marking already ready event as ready again', async () => {
        const contract = await createAndActivateContract();
        const event = await apiClient.createEvent(
          contract.id,
          createEventPayload(),
          coordinatorHeaders
        ).then(r => handleApiResponse<Event>(r, 201));

        const shift = await apiClient.createShift(
          contract.id,
          event.id,
          createShiftPayload(),
          coordinatorHeaders
        ).then(r => handleApiResponse<Shift>(r, 201));

        const staff = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload(),
          coordinatorHeaders
        ).then(r => handleApiResponse<StaffProfile>(r, 201));

        const assignment = await apiClient.createAssignment(
          contract.id,
          createAssignmentPayload(shift.id, staff.id),
          accountManagerHeaders
        ).then(r => handleApiResponse<Assignment>(r, 201));
        await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

        await apiClient.updateEventStatus(
          contract.id,
          event.id,
          { status: EventStatus.READY_FOR_EXECUTION },
          coordinatorHeaders
        );

        const res = await apiClient.updateEventStatus(
          contract.id,
          event.id,
          { status: EventStatus.READY_FOR_EXECUTION },
          coordinatorHeaders
        );

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ILLEGAL_EVENT_STATE_TRANSITION });
      });
    });

    describe('P3-EVENT-READY-01.4: Cannot cancel already cancelled event', () => {
      it('should reject cancelling an event that is already CANCELLED', async () => {
        const contract = await createAndActivateContract();
        const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));

        await apiClient.updateEventStatus(contract.id, event.id, { status: EventStatus.CANCELLED }, coordinatorHeaders);

        const res = await apiClient.updateEventStatus(contract.id, event.id, { status: EventStatus.CANCELLED }, coordinatorHeaders);

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ILLEGAL_EVENT_STATE_TRANSITION });
      });
    });

    describe('P3-EVENT-READY-01.5: Event parent mismatch', () => {
      it('should reject update if event does not belong to contract', async () => {
        const contractA = await createAndActivateContract();
        const contractB = await createAndActivateContract();
        const eventB = await apiClient.createEvent(contractB.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));

        const res = await apiClient.updateEventStatus(contractA.id, eventB.id, { status: EventStatus.CANCELLED }, coordinatorHeaders);

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_EVENT_NOT_FOUND });
      });
    });

    describe('P3-EVENT-READY-01.6: Cannot mark CANCELLED event as ready', () => {
      it('should reject marking CANCELLED event as READY_FOR_EXECUTION', async () => {
        const contract = await createAndActivateContract();
        const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));

        await apiClient.updateEventStatus(contract.id, event.id, { status: EventStatus.CANCELLED }, coordinatorHeaders);

        const res = await apiClient.updateEventStatus(
          contract.id,
          event.id,
          { status: EventStatus.READY_FOR_EXECUTION },
          coordinatorHeaders
        );

        validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_ILLEGAL_EVENT_STATE_TRANSITION });
      });
    });
  });

  describe('Rule: cascade-event-cancellation', () => {
    describe('P3-CASCADE-CANCEL-01.1: Cancel event cascades to shifts and assignments', () => {
      it('should cancel all shifts/assignments and revert ledgers when event cancelled', async () => {
        const contract = await createAndActivateContract(5000.00);

        const event1Res = await apiClient.createEvent(contract.id, createEventPayload({ name: "Unaffected Event" }), coordinatorHeaders);
        const event1 = handleApiResponse<Event>(event1Res, 201);
        const event2Res = await apiClient.createEvent(contract.id, createEventPayload({ name: "Cancelled Event" }), coordinatorHeaders);
        const event2 = handleApiResponse<Event>(event2Res, 201);

        const staffARes = await apiClient.createStaffProfile(
          contract.id,
          createStaffProfilePayload({ first_name: 'StaffA', base_pay_rate_per_hour: 20.00 }),
          coordinatorHeaders
        );
        const staffA = handleApiResponse<StaffProfile>(staffARes, 201);

        const baselineShiftRes = await apiClient.createShift(
          contract.id,
          event1.id,
          createShiftPayload({ role_name: 'Baseline Shift', start_time: 1700000000, end_time: 1700144000 }),
          coordinatorHeaders
        );
        const baselineShift = handleApiResponse<Shift>(baselineShiftRes, 201);
        const baselineAssignRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(baselineShift.id, staffA.id), accountManagerHeaders);
        const baselineAssign = handleApiResponse<Assignment>(baselineAssignRes, 201);
        await apiClient.acceptAssignment(contract.id, baselineAssign.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, baselineAssign.id, coordinatorHeaders);
        const baselineCost = 800.00;

        const shiftARes = await apiClient.createShift(
          contract.id,
          event2.id,
          createShiftPayload({ role_name: 'Shift A', start_time: 1700200000, end_time: 1700214400 }),
          coordinatorHeaders
        );
        const shiftA = handleApiResponse<Shift>(shiftARes, 201);
        const assignARes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftA.id, staffA.id), accountManagerHeaders);
        const assignA = handleApiResponse<Assignment>(assignARes, 201);

        const staffBRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: 'StaffB', base_pay_rate_per_hour: 25.00 }), coordinatorHeaders);
        const staffB = handleApiResponse<StaffProfile>(staffBRes, 201);
        const shiftBRes = await apiClient.createShift(
          contract.id,
          event2.id,
          createShiftPayload({ role_name: 'Shift B', start_time: 1700300000, end_time: 1700318000 }),
          coordinatorHeaders
        );
        const shiftB = handleApiResponse<Shift>(shiftBRes, 201);
        const assignBRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftB.id, staffB.id), accountManagerHeaders);
        const assignB = handleApiResponse<Assignment>(assignBRes, 201);
        await apiClient.acceptAssignment(contract.id, assignB.id, staffMemberHeaders);
        await apiClient.confirmAssignment(contract.id, assignB.id, coordinatorHeaders);

        const initialContract = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
        expect(initialContract.compliance_risk_score).toBe(5);
        expect(initialContract.budget_balance).toBe(5000.00 - baselineCost - (assignA.provisional_cost + assignB.provisional_cost));

        const cancelRes = await apiClient.updateEventStatus(
          contract.id,
          event2.id,
          { status: EventStatus.CANCELLED },
          coordinatorHeaders
        );
        const cancelledEvent = handleApiResponse<Event>(cancelRes, 200);

        expect(cancelledEvent.status).toBe(EventStatus.CANCELLED);

        const shiftACheckRes = await apiClient.getShift(contract.id, event2.id, shiftA.id, coordinatorHeaders);
        expect(handleApiResponse<Shift>(shiftACheckRes, 200).status).toBe(ShiftStatus.CANCELLED);
        const shiftBCheckRes = await apiClient.getShift(contract.id, event2.id, shiftB.id, coordinatorHeaders);
        expect(handleApiResponse<Shift>(shiftBCheckRes, 200).status).toBe(ShiftStatus.CANCELLED);

        const assignACheckRes = await apiClient.getAssignment(contract.id, assignA.id, coordinatorHeaders);
        expect(handleApiResponse<Assignment>(assignACheckRes, 200).status).toBe(AssignmentStatus.CANCELLED);
        const assignBCheckRes = await apiClient.getAssignment(contract.id, assignB.id, coordinatorHeaders);
        expect(handleApiResponse<Assignment>(assignBCheckRes, 200).status).toBe(AssignmentStatus.CANCELLED);

        const baselineAssignCheckRes = await apiClient.getAssignment(contract.id, baselineAssign.id, coordinatorHeaders);
        expect(handleApiResponse<Assignment>(baselineAssignCheckRes, 200).status).toBe(AssignmentStatus.CONFIRMED);

        const postContractRes = await apiClient.getContract(contract.id, coordinatorHeaders);
        const postContract = handleApiResponse<StaffingContract>(postContractRes, 200);

        expect(postContract.budget_balance).toBe(5000.00 - baselineCost);

        expect(postContract.compliance_risk_score).toBe(0);
      });
    });
  });
});
