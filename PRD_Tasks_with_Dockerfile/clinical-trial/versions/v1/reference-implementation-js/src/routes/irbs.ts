import { Router } from 'express';
import { db } from '../database';
import { ValidationService } from '../services/validators';
import { StateMachineService } from '../services/stateMachines';
import { asyncHandler, wrapResponse } from '../utils/helpers';
import { getResponseMeta } from '../middleware/requestContext';
import { researchDirectorOnly } from '../middleware/auth';
import { validateVersionIfProvided } from '../utils/occ';

const router = Router({ mergeParams: true });

router.post(
  '/',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { programId } = req.params;
    const { name, description } = req.body;

    const irb = db.createIRB({
      research_program_id: programId,
      name,
      description
    });

    res.status(201).json(
      wrapResponse('object', irb, getResponseMeta(req))
    );
  })
);

router.post(
  '/:irbId/approvals',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { programId, irbId } = req.params;
    const { trial_id } = req.body;

    ValidationService.validateIRBApprovalCreation(irbId, trial_id);

    const approval = db.createIRBApproval({
      irb_id: irbId,
      trial_id,
      research_program_id: programId
    });

    res.status(201).json(
      wrapResponse('object', approval, getResponseMeta(req))
    );
  })
);

router.put(
  '/:irbId/approvals/:approvalId',
  researchDirectorOnly,
  asyncHandler(async (req, res) => {
    const { approvalId } = req.params;
    const { status } = req.body;

    const approval = db.getIRBApproval(approvalId);

    validateVersionIfProvided(req, approval.version);

    ValidationService.validateIRBApprovalUpdate(status);

    StateMachineService.transitionIRBApproval(approvalId, status);

    res.status(200).json(
      wrapResponse('object', approval, getResponseMeta(req))
    );
  })
);

export default router;
